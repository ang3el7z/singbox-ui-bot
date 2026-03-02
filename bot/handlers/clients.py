"""Client management — thin wrapper over /api/clients/"""
import io
import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.api_client import clients_api, inbounds_api, APIError
from bot.keyboards.main import kb_back, kb_clients_list, kb_client_detail
from bot.utils import make_qr, format_bytes

router = Router()
PAGE_SIZE = 8


class AddClientFSM(StatesGroup):
    name = State()
    inbound = State()
    total_gb = State()
    expire_days = State()


@router.callback_query(F.data == "menu_clients")
async def cb_clients_menu(cq: CallbackQuery):
    try:
        clients = await clients_api.list()
        text = f"👥 <b>Clients</b> — total: {len(clients)}"
        mk = kb_clients_list(clients, page=0, page_size=PAGE_SIZE)
    except APIError as e:
        text = f"❌ {e.detail}"
        mk = kb_back("main_menu")
    await cq.message.edit_text(text, reply_markup=mk, parse_mode="HTML")


@router.callback_query(F.data.startswith("clients_page_"))
async def cb_clients_page(cq: CallbackQuery):
    page = int(cq.data.split("_")[-1])
    try:
        clients = await clients_api.list()
        mk = kb_clients_list(clients, page=page, page_size=PAGE_SIZE)
        await cq.message.edit_reply_markup(reply_markup=mk)
    except APIError:
        pass
    await cq.answer()


@router.callback_query(F.data.startswith("client_detail_"))
async def cb_client_detail(cq: CallbackQuery):
    cid = int(cq.data.split("_")[-1])
    try:
        c = await clients_api.get(cid)
        enabled = "✅" if c.get("enable") else "❌"
        up = format_bytes(c.get("upload", 0))
        down = format_bytes(c.get("download", 0))
        total = f"{c.get('total_gb', 0)} GB" if c.get('total_gb') else "∞"
        expiry = c.get("expiry_time")
        from datetime import datetime, timezone
        exp_str = datetime.fromtimestamp(expiry / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if expiry else "∞"
        text = (
            f"👤 <b>{c['name']}</b>\n"
            f"Protocol: {c.get('protocol', '?')}\n"
            f"Inbound: {c.get('inbound_tag', '?')}\n"
            f"Status: {enabled}\n"
            f"Traffic: ↑{up} / ↓{down}\n"
            f"Limit: {total}\n"
            f"Expires: {exp_str}\n"
            f"Sub ID: <code>{c.get('sub_id', '')}</code>"
        )
    except APIError as e:
        text = f"❌ {e.detail}"
        cid = 0
    await cq.message.edit_text(text, reply_markup=kb_client_detail(cid), parse_mode="HTML")


@router.callback_query(F.data.startswith("client_toggle_"))
async def cb_client_toggle(cq: CallbackQuery):
    cid = int(cq.data.split("_")[-1])
    try:
        c = await clients_api.get(cid)
        new_state = not c.get("enable", True)
        await clients_api.update(cid, enable=new_state)
        await cq.answer("✅ Updated")
        await cb_client_detail.__wrapped__(cq) if hasattr(cb_client_detail, "__wrapped__") else None
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data.startswith("client_qr_"))
async def cb_client_qr(cq: CallbackQuery):
    cid = int(cq.data.split("_")[-1])
    try:
        sub_cfg = await clients_api.subscription(cid)
        sub_json = json.dumps(sub_cfg, indent=2)
        try:
            qr_file = make_qr(sub_json)
            await cq.message.answer_photo(qr_file, caption="📱 Scan to import config")
        except Exception:
            await cq.message.answer("❌ Failed to generate QR")
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}")
    await cq.answer()


@router.callback_query(F.data.startswith("client_sub_"))
async def cb_client_sub(cq: CallbackQuery):
    cid = int(cq.data.split("_")[-1])
    try:
        sub_cfg = await clients_api.subscription(cid)
        sub_json = json.dumps(sub_cfg, indent=2, ensure_ascii=False)
        file = BufferedInputFile(sub_json.encode("utf-8"), filename="config.json")
        await cq.message.answer_document(file, caption="📄 Sing-Box client config")
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}")
    await cq.answer()


@router.callback_query(F.data.startswith("client_reset_stats_"))
async def cb_client_reset_stats(cq: CallbackQuery):
    cid = int(cq.data.split("_")[-1])
    try:
        await clients_api.reset_stats(cid)
        await cq.answer("✅ Stats reset")
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data.startswith("client_delete_"))
async def cb_client_delete(cq: CallbackQuery):
    cid = int(cq.data.split("_")[-1])
    try:
        await clients_api.delete(cid)
        await cq.answer("✅ Deleted")
        await cq.message.edit_text("✅ Client deleted", reply_markup=kb_back("menu_clients"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── Add client FSM ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "client_add")
async def cb_client_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddClientFSM.name)
    await cq.message.answer("Enter client name:")
    await cq.answer()


@router.message(AddClientFSM.name)
async def fsm_client_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    try:
        inbounds = await inbounds_api.list()
        if not inbounds:
            await msg.answer("❌ No inbounds configured. Add an inbound first.")
            await state.clear()
            return
        from bot.keyboards.main import kb_inbound_select
        await msg.answer("Choose inbound:", reply_markup=kb_inbound_select(inbounds, "addclient"))
        await state.set_state(AddClientFSM.inbound)
    except APIError as e:
        await msg.answer(f"❌ {e.detail}")
        await state.clear()


@router.callback_query(AddClientFSM.inbound, F.data.startswith("addclient_inbound_"))
async def fsm_client_inbound(cq: CallbackQuery, state: FSMContext):
    tag = cq.data.replace("addclient_inbound_", "")
    await state.update_data(inbound_tag=tag)
    await state.set_state(AddClientFSM.total_gb)
    await cq.message.answer("Traffic limit (GB), 0 = unlimited:")
    await cq.answer()


@router.message(AddClientFSM.total_gb)
async def fsm_client_gb(msg: Message, state: FSMContext):
    try:
        gb = float(msg.text.strip())
    except ValueError:
        await msg.answer("Enter a number:")
        return
    await state.update_data(total_gb=gb)
    await state.set_state(AddClientFSM.expire_days)
    await msg.answer("Expire in days, 0 = no expiry:")


@router.message(AddClientFSM.expire_days)
async def fsm_client_expire(msg: Message, state: FSMContext):
    try:
        days = int(msg.text.strip())
    except ValueError:
        await msg.answer("Enter a number:")
        return
    data = await state.get_data()
    await state.clear()
    try:
        c = await clients_api.create(
            name=data["name"],
            inbound_tag=data["inbound_tag"],
            total_gb=data.get("total_gb", 0),
            expire_days=days,
        )
        await msg.answer(
            f"✅ Client <b>{c['name']}</b> created\n"
            f"Protocol: {c['protocol']}\n"
            f"Sub ID: <code>{c['sub_id']}</code>",
            parse_mode="HTML",
            reply_markup=kb_back("menu_clients"),
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_clients"))
