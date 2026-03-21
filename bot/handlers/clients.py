"""Client management — thin wrapper over /api/clients/"""
import io
import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from api.routers.settings_router import get_runtime
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


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


@router.callback_query(F.data == "menu_clients")
async def cb_clients_menu(cq: CallbackQuery):
    try:
        clients = await clients_api.list()
        text = _txt(
            f"👥 <b>Клиенты</b> — всего: {len(clients)}",
            f"👥 <b>Clients</b> — total: {len(clients)}",
        )
        mk = kb_clients_list(clients, page=0, page_size=PAGE_SIZE)
    except APIError as e:
        text = f"❌ {e.detail}"
        mk = kb_back("menu_server")
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
            f"{_txt('Протокол', 'Protocol')}: {c.get('protocol', '?')}\n"
            f"{_txt('Inbound', 'Inbound')}: {c.get('inbound_tag', '?')}\n"
            f"{_txt('Статус', 'Status')}: {enabled}\n"
            f"{_txt('Трафик', 'Traffic')}: ↑{up} / ↓{down}\n"
            f"{_txt('Лимит', 'Limit')}: {total}\n"
            f"{_txt('Истекает', 'Expires')}: {exp_str}\n"
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
        await cq.answer(_txt("✅ Обновлено", "✅ Updated"))
        await cb_client_detail.__wrapped__(cq) if hasattr(cb_client_detail, "__wrapped__") else None
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data.startswith("client_suburl_"))
async def cb_client_suburl(cq: CallbackQuery):
    """Show subscription URL and QR code for direct import into sing-box apps."""
    cid = int(cq.data.split("_")[-1])
    try:
        data = await clients_api.sub_url(cid)
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}")
        await cq.answer()
        return

    sub_url     = data.get("url", "")
    windows_zip = data.get("windows_zip", "")

    text = (
        _txt(
            "🔗 <b>Ссылка подписки</b>\n\n"
            "Вставьте в sing-box / nekobox / clash-meta:\n",
            "🔗 <b>Subscription link</b>\n\n"
            "Paste into sing-box / nekobox / clash-meta:\n",
        )
        + f"<code>{sub_url}</code>\n\n"
        + _txt(
            "🪟 <b>Windows Service — готовый архив</b>\n"
            "Скачай ZIP → распакуй → запусти <code>install.cmd</code> от Администратора:\n",
            "🪟 <b>Windows Service — ready archive</b>\n"
            "Download ZIP → extract → run <code>install.cmd</code> as Administrator:\n",
        )
        + f"<code>{windows_zip}</code>\n\n"
        + _txt(
            "<i>Архив содержит sing-box.exe, winsw3.exe и все скрипты.\n"
            "Конфиг загружается с сервера автоматически при каждом старте.</i>",
            "<i>The archive includes sing-box.exe, winsw3.exe, and all scripts.\n"
            "Config is fetched from the server automatically on each start.</i>",
        )
    )
    await cq.message.answer(text, parse_mode="HTML")

    # QR for sub URL
    if sub_url:
        try:
            qr_file = make_qr(sub_url)
            await cq.message.answer_photo(
                qr_file,
                caption=_txt("📱 Сканируйте для импорта подписки", "📱 Scan to import subscription"),
            )
        except Exception:
            pass

    await cq.answer()


@router.callback_query(F.data.startswith("client_sub_"))
async def cb_client_sub(cq: CallbackQuery):
    """Download config using the client's assigned template (or default)."""
    cid = int(cq.data.split("_")[-1])
    try:
        sub_cfg = await clients_api.subscription(cid)
        sub_json = json.dumps(sub_cfg, indent=2, ensure_ascii=False)
        file = BufferedInputFile(sub_json.encode("utf-8"), filename="config.json")
        await cq.message.answer_document(
            file,
            caption=_txt(
                "📄 Конфиг клиента Sing-Box\n"
                "<i>Чтобы сменить шаблон: карточка клиента → 🎨 Шаблон</i>",
                "📄 Sing-Box client config\n"
                "<i>To change template: client detail → 🎨 Template</i>",
            ),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}")
    await cq.answer()


@router.callback_query(F.data.startswith("client_reset_stats_"))
async def cb_client_reset_stats(cq: CallbackQuery):
    cid = int(cq.data.split("_")[-1])
    try:
        await clients_api.reset_stats(cid)
        await cq.answer(_txt("✅ Статистика сброшена", "✅ Stats reset"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data.startswith("client_delete_"))
async def cb_client_delete(cq: CallbackQuery):
    cid = int(cq.data.split("_")[-1])
    try:
        await clients_api.delete(cid)
        await cq.answer(_txt("✅ Удалено", "✅ Deleted"))
        await cq.message.edit_text(
            _txt("✅ Клиент удалён", "✅ Client deleted"),
            reply_markup=kb_back("menu_clients"),
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── Add client FSM ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "client_add")
async def cb_client_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddClientFSM.name)
    await cq.message.answer(_txt("Введите имя клиента:", "Enter client name:"))
    await cq.answer()


@router.message(AddClientFSM.name)
async def fsm_client_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    try:
        inbounds = await inbounds_api.list()
        if not inbounds:
            await msg.answer(_txt("❌ Inbounds не настроены. Сначала добавьте inbound.", "❌ No inbounds configured. Add an inbound first."))
            await state.clear()
            return
        from bot.keyboards.main import kb_inbound_select
        await msg.answer(_txt("Выберите inbound:", "Choose inbound:"), reply_markup=kb_inbound_select(inbounds, "addclient"))
        await state.set_state(AddClientFSM.inbound)
    except APIError as e:
        await msg.answer(f"❌ {e.detail}")
        await state.clear()


@router.callback_query(AddClientFSM.inbound, F.data.startswith("addclient_inbound_"))
async def fsm_client_inbound(cq: CallbackQuery, state: FSMContext):
    tag = cq.data.replace("addclient_inbound_", "")
    await state.update_data(inbound_tag=tag)
    await state.set_state(AddClientFSM.total_gb)
    await cq.message.answer(_txt("Лимит трафика (GB), 0 = безлимит:", "Traffic limit (GB), 0 = unlimited:"))
    await cq.answer()


@router.message(AddClientFSM.total_gb)
async def fsm_client_gb(msg: Message, state: FSMContext):
    try:
        gb = float(msg.text.strip())
    except ValueError:
        await msg.answer(_txt("Введите число:", "Enter a number:"))
        return
    await state.update_data(total_gb=gb)
    await state.set_state(AddClientFSM.expire_days)
    await msg.answer(_txt("Срок действия в днях, 0 = без ограничения:", "Expire in days, 0 = no expiry:"))


@router.message(AddClientFSM.expire_days)
async def fsm_client_expire(msg: Message, state: FSMContext):
    try:
        days = int(msg.text.strip())
    except ValueError:
        await msg.answer(_txt("Введите число:", "Enter a number:"))
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
            _txt(
                f"✅ Клиент <b>{c['name']}</b> создан\n"
                f"Протокол: {c['protocol']}\n",
                f"✅ Client <b>{c['name']}</b> created\n"
                f"Protocol: {c['protocol']}\n",
            )
            + f"Sub ID: <code>{c['sub_id']}</code>",
            parse_mode="HTML",
            reply_markup=kb_back("menu_clients"),
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_clients"))
