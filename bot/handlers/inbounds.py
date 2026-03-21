"""Inbound management — thin wrapper over /api/inbounds/"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from api.routers.settings_router import get_runtime
from bot.api_client import inbounds_api, APIError
from bot.keyboards.main import kb_back, kb_inbounds_list, kb_inbound_detail, kb_protocol_select

router = Router()

PROTOCOLS = ["vless_reality", "vless_ws", "vmess_ws", "trojan", "shadowsocks", "hysteria2", "tuic"]


class AddInboundFSM(StatesGroup):
    protocol = State()
    tag = State()
    port = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


@router.callback_query(F.data == "menu_inbounds")
async def cb_inbounds_menu(cq: CallbackQuery):
    try:
        inbounds = await inbounds_api.list()
        text = _txt(
            f"🔌 <b>Inbounds</b> — всего: {len(inbounds)}",
            f"🔌 <b>Inbounds</b> — total: {len(inbounds)}",
        )
        mk = kb_inbounds_list(inbounds)
    except APIError as e:
        text = f"❌ {e.detail}"
        mk = kb_back("main_menu")
    await cq.message.edit_text(text, reply_markup=mk, parse_mode="HTML")


@router.callback_query(F.data.startswith("inbound_detail_"))
async def cb_inbound_detail(cq: CallbackQuery):
    tag = cq.data.replace("inbound_detail_", "")
    try:
        ib = await inbounds_api.get(tag)
        proto = ib.get("type", "?")
        port = ib.get("listen_port", "?")
        users = len(ib.get("users", []))
        text = (
            f"🔌 <b>{tag}</b>\n"
            f"{_txt('Протокол', 'Protocol')}: {proto}\n"
            f"{_txt('Порт', 'Port')}: {port}\n"
            f"{_txt('Пользователи', 'Users')}: {users}"
        )
    except APIError as e:
        text = f"❌ {e.detail}"
        tag = ""
    await cq.message.edit_text(text, reply_markup=kb_inbound_detail(tag), parse_mode="HTML")


@router.callback_query(F.data.startswith("inbound_delete_"))
async def cb_inbound_delete(cq: CallbackQuery):
    tag = cq.data.replace("inbound_delete_", "")
    try:
        await inbounds_api.delete(tag)
        await cq.answer(_txt("✅ Удалено", "✅ Deleted"))
        await cq.message.edit_text(
            _txt("✅ Inbound удалён", "✅ Inbound deleted"),
            reply_markup=kb_back("menu_inbounds"),
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data == "inbound_add")
async def cb_inbound_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddInboundFSM.protocol)
    await cq.message.answer(
        _txt("Выберите протокол:", "Choose protocol:"),
        reply_markup=kb_protocol_select(PROTOCOLS, "addinbound"),
    )
    await cq.answer()


@router.callback_query(AddInboundFSM.protocol, F.data.startswith("addinbound_proto_"))
async def fsm_inbound_proto(cq: CallbackQuery, state: FSMContext):
    proto = cq.data.replace("addinbound_proto_", "")
    await state.update_data(protocol=proto)
    await state.set_state(AddInboundFSM.tag)
    await cq.message.answer(
        _txt(
            f"Протокол: <b>{proto}</b>\nВведите тег (уникальное имя, например vless-in):",
            f"Protocol: <b>{proto}</b>\nEnter tag (unique name, e.g. vless-in):",
        ),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(AddInboundFSM.tag)
async def fsm_inbound_tag(msg: Message, state: FSMContext):
    tag = msg.text.strip().replace(" ", "_")
    await state.update_data(tag=tag)
    await state.set_state(AddInboundFSM.port)
    await msg.answer(
        _txt(
            f"Тег: <b>{tag}</b>\nВведите порт прослушивания (1–65535):",
            f"Tag: <b>{tag}</b>\nEnter listen port (1–65535):",
        ),
        parse_mode="HTML",
    )


@router.message(AddInboundFSM.port)
async def fsm_inbound_port(msg: Message, state: FSMContext):
    try:
        port = int(msg.text.strip())
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        await msg.answer(_txt("Введите корректный порт (1–65535):", "Enter a valid port number (1–65535):"))
        return
    data = await state.get_data()
    await state.clear()
    try:
        ib = await inbounds_api.create(
            tag=data["tag"],
            protocol=data["protocol"],
            listen_port=port,
        )
        proto = ib.get("type", data["protocol"])
        text = (
            _txt(
                f"✅ Inbound <b>{data['tag']}</b> создан\n"
                f"Протокол: {proto}\n"
                f"Порт: {port}",
                f"✅ Inbound <b>{data['tag']}</b> created\n"
                f"Protocol: {proto}\n"
                f"Port: {port}",
            )
        )
        # For Reality, show public key
        tls = ib.get("tls", {})
        reality = tls.get("reality", {})
        if reality.get("public_key"):
            text += _txt(
                f"\n🔑 Публичный ключ: <code>{reality['public_key']}</code>",
                f"\n🔑 Public key: <code>{reality['public_key']}</code>",
            )
            short_ids = reality.get("short_id", [])
            if short_ids:
                text += _txt(
                    f"\nShort ID: <code>{short_ids[0]}</code>",
                    f"\nShort ID: <code>{short_ids[0]}</code>",
                )
    except APIError as e:
        text = f"❌ {e.detail}"
    await msg.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_inbounds"))
