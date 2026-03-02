import json
from typing import Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services.sui_api import sui, SuiAPIError
from bot.keyboards.main import back_kb, paginate_kb
from bot.texts import t
from bot.utils import paginate
from bot.middleware.auth import log_action

router = Router()

ITEMS_PER_PAGE = 8

PROTOCOLS = [
    ("VLESS Reality", "vless_reality"),
    ("VLESS WebSocket", "vless_ws"),
    ("VMess WS", "vmess_ws"),
    ("Shadowsocks", "shadowsocks"),
    ("Trojan", "trojan"),
    ("Hysteria2", "hysteria2"),
    ("TUIC v5", "tuic"),
]


class AddInboundFSM(StatesGroup):
    waiting_tag = State()
    waiting_port = State()
    waiting_protocol = State()


# ─── Inbound templates ────────────────────────────────────────────────────────

def build_inbound_template(protocol: str, tag: str, port: int) -> dict:
    base = {"tag": tag, "type": protocol.split("_")[0], "listen": "0.0.0.0", "listen_port": port, "enable": True}
    if protocol == "vless_reality":
        base.update({
            "type": "vless",
            "users": [],
            "tls": {
                "enabled": True,
                "server_name": "www.microsoft.com",
                "reality": {
                    "enabled": True,
                    "handshake": {"server": "www.microsoft.com", "server_port": 443},
                    "private_key": "",
                    "short_id": [""],
                },
            },
            "multiplex": {"enabled": True, "padding": True},
        })
    elif protocol == "vless_ws":
        base.update({
            "type": "vless",
            "users": [],
            "transport": {"type": "ws", "path": f"/{tag}"},
        })
    elif protocol == "vmess_ws":
        base.update({
            "type": "vmess",
            "users": [],
            "transport": {"type": "ws", "path": f"/{tag}"},
        })
    elif protocol == "shadowsocks":
        base.update({
            "type": "shadowsocks",
            "method": "aes-256-gcm",
            "password": "",
            "users": [],
            "multiplex": {"enabled": True},
        })
    elif protocol == "trojan":
        base.update({
            "type": "trojan",
            "users": [],
            "tls": {"enabled": True},
            "transport": {"type": "ws", "path": f"/{tag}"},
        })
    elif protocol == "hysteria2":
        base.update({
            "type": "hysteria2",
            "users": [],
            "tls": {"enabled": True},
            "up_mbps": 100,
            "down_mbps": 100,
        })
    elif protocol == "tuic":
        base.update({
            "type": "tuic",
            "users": [],
            "tls": {"enabled": True},
            "congestion_control": "bbr",
        })
    return base


# ─── Menu ──────────────────────────────────────────────────────────────────────

def inbounds_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("inbounds_list"), callback_data="inbounds:list:1"),
        InlineKeyboardButton(text=t("inbounds_add"), callback_data="inbounds:add"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:inbounds")
async def cb_inbounds_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(t("inbounds_menu"), reply_markup=inbounds_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ─── List ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("inbounds:list:"))
async def cb_inbounds_list(callback: CallbackQuery) -> None:
    await callback.answer()
    page = int(callback.data.split(":")[2])
    try:
        inbounds = await sui.get_inbounds()
    except SuiAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:inbounds"))
        return

    if not inbounds:
        await callback.message.edit_text(
            "📡 Нет inbounds.",
            reply_markup=back_kb("menu:inbounds"),
        )
        return

    page_items, page, total_pages = paginate(inbounds, page, ITEMS_PER_PAGE)
    items = []
    for ib in page_items:
        iid = ib.get("id", 0)
        tag = ib.get("tag", "?")
        proto = ib.get("type", "?")
        port = ib.get("listen_port", "?")
        active = "✅" if ib.get("enable", True) else "⛔"
        items.append({
            "label": f"{active} [{proto}] {tag} :{port}",
            "callback_data": f"inbound:view:{iid}",
        })

    kb = paginate_kb(items, page, total_pages, "inbounds:list", back_cb="menu:inbounds")
    await callback.message.edit_text(
        f"📡 <b>Inbounds</b> [{len(inbounds)}] • Стр. {page}/{total_pages}",
        reply_markup=kb,
        parse_mode="HTML",
    )


# ─── View single inbound ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("inbound:view:"))
async def cb_inbound_view(callback: CallbackQuery) -> None:
    await callback.answer()
    iid = int(callback.data.split(":")[2])
    try:
        inbounds = await sui.get_inbounds(iid)
        if isinstance(inbounds, list):
            inbound = next((x for x in inbounds if x.get("id") == iid), None)
        else:
            inbound = inbounds
        if not inbound:
            await callback.message.edit_text(t("error", msg="Not found"), reply_markup=back_kb("inbounds:list:1"))
            return
    except SuiAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("inbounds:list:1"))
        return

    tag = inbound.get("tag", "?")
    proto = inbound.get("type", "?")
    port = inbound.get("listen_port", "?")
    enabled = inbound.get("enable", True)
    clients = inbound.get("users", [])
    tls_enabled = inbound.get("tls", {}).get("enabled", False)

    text = (
        f"📡 <b>Inbound: {tag}</b>\n\n"
        f"▪ Протокол: <code>{proto}</code>\n"
        f"▪ Порт: <code>{port}</code>\n"
        f"▪ TLS: {'✅' if tls_enabled else '❌'}\n"
        f"▪ Статус: {'✅ активен' if enabled else '⛔ выключен'}\n"
        f"▪ Клиентов: {len(clients) if isinstance(clients, list) else 0}"
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("disable") if enabled else t("enable"),
            callback_data=f"inbound:toggle:{iid}",
        ),
        InlineKeyboardButton(text=t("delete"), callback_data=f"inbound:delete_confirm:{iid}"),
    )
    builder.row(
        InlineKeyboardButton(text=t("refresh"), callback_data=f"inbound:view:{iid}"),
        InlineKeyboardButton(text=t("back"), callback_data="inbounds:list:1"),
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ─── Toggle ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("inbound:toggle:"))
async def cb_inbound_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    iid = int(callback.data.split(":")[2])
    try:
        inbounds = await sui.get_inbounds(iid)
        if isinstance(inbounds, list):
            inbound = next((x for x in inbounds if x.get("id") == iid), None)
        else:
            inbound = inbounds
        if not inbound:
            return
        new_state = not inbound.get("enable", True)
        inbound["enable"] = new_state
        await sui.save_inbound(inbound)
        await log_action(callback.from_user.id, "toggle_inbound", f"id={iid} enable={new_state}")
        text = t("inbound_enabled") if new_state else t("inbound_disabled")
        await callback.message.edit_text(text, reply_markup=back_kb(f"inbound:view:{iid}"), parse_mode="HTML")
    except SuiAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Delete ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("inbound:delete_confirm:"))
async def cb_inbound_delete_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    iid = int(callback.data.split(":")[2])
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"inbound:delete:{iid}"),
        InlineKeyboardButton(text=t("cancel"), callback_data=f"inbound:view:{iid}"),
    )
    await callback.message.edit_text(f"❓ Удалить inbound #{iid}?", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("inbound:delete:"))
async def cb_inbound_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    iid = int(callback.data.split(":")[2])
    try:
        await sui.delete_inbound(iid)
        await log_action(callback.from_user.id, "delete_inbound", f"id={iid}")
        await callback.message.edit_text(t("inbound_deleted"), reply_markup=back_kb("inbounds:list:1"))
    except SuiAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Add inbound FSM ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "inbounds:add")
async def cb_inbounds_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AddInboundFSM.waiting_tag)
    await callback.message.answer(t("ask_inbound_tag"), reply_markup=back_kb("menu:inbounds"))


@router.message(AddInboundFSM.waiting_tag)
async def fsm_inbound_tag(message: Message, state: FSMContext) -> None:
    tag = message.text.strip().replace(" ", "_")
    await state.update_data(tag=tag)
    await state.set_state(AddInboundFSM.waiting_port)
    await message.answer(t("ask_inbound_port"), reply_markup=back_kb("menu:inbounds"))


@router.message(AddInboundFSM.waiting_port)
async def fsm_inbound_port(message: Message, state: FSMContext) -> None:
    try:
        port = int(message.text.strip())
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        await message.answer("Введите корректный порт (1-65535).")
        return
    await state.update_data(port=port)
    await state.set_state(AddInboundFSM.waiting_protocol)

    builder = InlineKeyboardBuilder()
    for label, proto_key in PROTOCOLS:
        builder.row(InlineKeyboardButton(text=label, callback_data=f"inbound:proto:{proto_key}"))
    builder.row(InlineKeyboardButton(text=t("cancel"), callback_data="menu:inbounds"))
    await message.answer(t("select_protocol"), reply_markup=builder.as_markup())


@router.callback_query(AddInboundFSM.waiting_protocol, F.data.startswith("inbound:proto:"))
async def fsm_inbound_protocol(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    proto = callback.data.split(":")[2]
    data = await state.get_data()
    await state.clear()

    tag = data["tag"]
    port = data["port"]
    inbound_data = build_inbound_template(proto, tag, port)

    try:
        await sui.save_inbound(inbound_data)
        await log_action(callback.from_user.id, "add_inbound", f"tag={tag} proto={proto} port={port}")
        await callback.message.edit_text(
            f"✅ Inbound <b>{tag}</b> [{proto}] :{port} создан",
            reply_markup=back_kb("inbounds:list:1"),
            parse_mode="HTML",
        )
    except SuiAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:inbounds"))
