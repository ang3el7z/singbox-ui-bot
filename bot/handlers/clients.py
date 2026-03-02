import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services.sui_api import sui, SuiAPIError
from bot.keyboards.main import back_kb, paginate_kb
from bot.texts import t
from bot.utils import format_bytes, make_qr, paginate
from bot.middleware.auth import log_action

router = Router()

ITEMS_PER_PAGE = 8


class AddClientFSM(StatesGroup):
    waiting_name = State()
    waiting_limit = State()
    waiting_expire = State()


# ─── Menu ──────────────────────────────────────────────────────────────────────

def clients_menu_kb(page: int = 1) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("clients_list"), callback_data=f"clients:list:1"),
        InlineKeyboardButton(text=t("clients_add"), callback_data="clients:add"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:clients")
async def cb_clients_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(t("clients_menu"), reply_markup=clients_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ─── List ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("clients:list:"))
async def cb_clients_list(callback: CallbackQuery) -> None:
    await callback.answer()
    page = int(callback.data.split(":")[2])
    try:
        clients = await sui.get_clients()
        stats_obj = await sui.get_stats(resource="client")
    except SuiAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:clients"))
        return

    if not clients:
        await callback.message.edit_text(
            t("clients_empty"),
            reply_markup=back_kb("menu:clients"),
            parse_mode="HTML",
        )
        return

    stats_map = {}
    if isinstance(stats_obj, list):
        for s in stats_obj:
            stats_map[s.get("tag", "")] = s

    page_items, page, total_pages = paginate(clients, page, ITEMS_PER_PAGE)

    items = []
    for c in page_items:
        name = c.get("name", c.get("email", "?"))
        cid = c.get("id", 0)
        tag = c.get("tag", "")
        st = stats_map.get(tag, {})
        dl = format_bytes(st.get("down", 0))
        ul = format_bytes(st.get("up", 0))
        active = "✅" if c.get("enable", True) else "⛔"
        items.append({
            "label": f"{active} {name} | ↓{dl} ↑{ul}",
            "callback_data": f"client:view:{cid}",
        })

    kb = paginate_kb(items, page, total_pages, "clients:list", back_cb="menu:clients")
    await callback.message.edit_text(
        f"👥 <b>Клиенты</b> [{len(clients)}] • Стр. {page}/{total_pages}",
        reply_markup=kb,
        parse_mode="HTML",
    )


# ─── View single client ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("client:view:"))
async def cb_client_view(callback: CallbackQuery) -> None:
    await callback.answer()
    client_id = int(callback.data.split(":")[2])
    try:
        client = await sui.get_clients(client_id)
        if isinstance(client, list):
            client = next((c for c in client if c.get("id") == client_id), None)
        if not client:
            await callback.message.edit_text(t("error", msg="Client not found"), reply_markup=back_kb("clients:list:1"))
            return
        stats_obj = await sui.get_stats(resource="client", tag=client.get("tag", ""))
        if isinstance(stats_obj, list) and stats_obj:
            st = stats_obj[0]
        elif isinstance(stats_obj, dict):
            st = stats_obj
        else:
            st = {}
    except SuiAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("clients:list:1"))
        return

    name = client.get("name", client.get("email", "?"))
    dl = format_bytes(st.get("down", 0))
    ul = format_bytes(st.get("up", 0))
    limit_bytes = client.get("totalGB", 0)
    limit = format_bytes(limit_bytes * 1024**3) if limit_bytes else "∞"
    expire_days = client.get("expiryTime", 0)
    if expire_days:
        expire_dt = datetime.fromtimestamp(expire_days / 1000) if expire_days > 1e9 else datetime.now() + timedelta(days=expire_days)
        expire_str = expire_dt.strftime("%Y-%m-%d")
    else:
        expire_str = "∞"

    text = t(
        "client_info",
        name=name,
        dl=dl,
        ul=ul,
        limit=limit,
        expire=expire_str,
        active="✅" if client.get("enable", True) else "⛔",
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("qr_code"), callback_data=f"client:qr:{client_id}"),
        InlineKeyboardButton(text=t("subscription"), callback_data=f"client:sub:{client_id}"),
    )
    builder.row(
        InlineKeyboardButton(text=t("refresh"), callback_data=f"client:view:{client_id}"),
        InlineKeyboardButton(
            text=t("disable") if client.get("enable", True) else t("enable"),
            callback_data=f"client:toggle:{client_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Сброс статистики", callback_data=f"client:resetstats:{client_id}"),
        InlineKeyboardButton(text=t("delete"), callback_data=f"client:delete_confirm:{client_id}"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="clients:list:1"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ─── QR code ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("client:qr:"))
async def cb_client_qr(callback: CallbackQuery) -> None:
    await callback.answer()
    client_id = int(callback.data.split(":")[2])
    try:
        client = await sui.get_clients(client_id)
        if isinstance(client, list):
            client = next((c for c in client if c.get("id") == client_id), {})
        sub_id = client.get("subId", "")
        if not sub_id:
            await callback.message.answer(t("error", msg="No sub ID"))
            return
        sub_content = await sui.get_subscription(sub_id, "json")
        config = json.loads(sub_content)
        # Use first outbound link if available
        outbounds = config.get("outbounds", [])
        link = ""
        for ob in outbounds:
            if ob.get("type") not in ("direct", "block", "dns"):
                tag = ob.get("tag", "")
                link = f"sing-box://import-remote-profile/?url={sub_id}#{tag}"
                break
        if not link:
            link = f"sing-box://import-remote-profile/?url={sub_id}"
        qr = make_qr(link, filename=f"client_{client_id}.png")
        await callback.message.answer_photo(qr, caption=f"<code>{link}</code>", parse_mode="HTML")
    except SuiAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Subscription link ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("client:sub:"))
async def cb_client_sub(callback: CallbackQuery) -> None:
    await callback.answer()
    client_id = int(callback.data.split(":")[2])
    try:
        from bot.config import settings
        client = await sui.get_clients(client_id)
        if isinstance(client, list):
            client = next((c for c in client if c.get("id") == client_id), {})
        sub_id = client.get("subId", "")
        if not sub_id:
            await callback.message.answer(t("error", msg="No subscription ID"))
            return
        base = settings.sui_url.replace("http://sui:", f"https://{settings.domain}:")
        builder = InlineKeyboardBuilder()
        links = [
            ("Sing-Box JSON", f"{settings.bot_public_url}/sub/{sub_id}?format=json"),
            ("Clash Meta", f"{settings.bot_public_url}/sub/{sub_id}?format=clash"),
            ("Raw", f"{settings.bot_public_url}/sub/{sub_id}"),
        ]
        text_lines = [f"🔗 <b>Подписки для клиента #{client_id}</b>\n"]
        for label, url in links:
            text_lines.append(f"<b>{label}:</b>\n<code>{url}</code>")
        await callback.message.answer("\n\n".join(text_lines), parse_mode="HTML")
    except SuiAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Toggle enable ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("client:toggle:"))
async def cb_client_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    client_id = int(callback.data.split(":")[2])
    try:
        clients = await sui.get_clients(client_id)
        if isinstance(clients, list):
            client = next((c for c in clients if c.get("id") == client_id), None)
        else:
            client = clients
        if not client:
            return
        new_state = not client.get("enable", True)
        client["enable"] = new_state
        await sui.save_client(client)
        await log_action(callback.from_user.id, "toggle_client", f"id={client_id} enable={new_state}")
        await callback.message.edit_text(
            t("inbound_enabled") if new_state else t("inbound_disabled"),
            reply_markup=back_kb(f"client:view:{client_id}"),
            parse_mode="HTML",
        )
    except SuiAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Reset stats ───────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("client:resetstats:"))
async def cb_client_reset_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    client_id = int(callback.data.split(":")[2])
    try:
        await sui.reset_client_stats(client_id)
        await log_action(callback.from_user.id, "reset_client_stats", f"id={client_id}")
        await callback.message.answer(t("client_stats_reset"))
    except SuiAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Delete client ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("client:delete_confirm:"))
async def cb_client_delete_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    client_id = int(callback.data.split(":")[2])
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"client:delete:{client_id}"),
        InlineKeyboardButton(text=t("cancel"), callback_data=f"client:view:{client_id}"),
    )
    await callback.message.edit_text(
        f"❓ Удалить клиента #{client_id}?",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("client:delete:"))
async def cb_client_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    client_id = int(callback.data.split(":")[2])
    try:
        await sui.delete_client(client_id)
        await log_action(callback.from_user.id, "delete_client", f"id={client_id}")
        await callback.message.edit_text(t("client_deleted"), reply_markup=back_kb("clients:list:1"))
    except SuiAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Add client FSM ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "clients:add")
async def cb_clients_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AddClientFSM.waiting_name)
    await callback.message.answer(
        t("ask_client_name"),
        reply_markup=back_kb("menu:clients"),
    )


@router.message(AddClientFSM.waiting_name)
async def fsm_client_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(AddClientFSM.waiting_limit)
    await message.answer(t("ask_client_limit"), reply_markup=back_kb("menu:clients"))


@router.message(AddClientFSM.waiting_limit)
async def fsm_client_limit(message: Message, state: FSMContext) -> None:
    try:
        limit = float(message.text.strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(limit=limit)
    await state.set_state(AddClientFSM.waiting_expire)
    await message.answer(t("ask_client_expire"), reply_markup=back_kb("menu:clients"))


@router.message(AddClientFSM.waiting_expire)
async def fsm_client_expire(message: Message, state: FSMContext) -> None:
    try:
        expire_days = int(message.text.strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return

    data = await state.get_data()
    await state.clear()

    name = data["name"]
    limit_gb = data["limit"]
    expire_ms = 0
    if expire_days > 0:
        expire_dt = datetime.now() + timedelta(days=expire_days)
        expire_ms = int(expire_dt.timestamp() * 1000)

    client_data = {
        "name": name,
        "email": name.lower().replace(" ", "_"),
        "subId": uuid.uuid4().hex[:16],
        "totalGB": limit_gb,
        "expiryTime": expire_ms,
        "enable": True,
        "tgId": "",
        "reset": 0,
    }
    try:
        await sui.save_client(client_data)
        await log_action(message.from_user.id, "add_client", f"name={name}")
        await message.answer(t("client_added", name=name), reply_markup=back_kb("clients:list:1"), parse_mode="HTML")
    except SuiAPIError as e:
        await message.answer(t("error", msg=str(e)))
