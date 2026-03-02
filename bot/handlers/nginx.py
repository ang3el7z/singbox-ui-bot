"""Nginx management — thin wrapper over /api/nginx/"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, Document
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from bot.api_client import nginx_api, APIError
from bot.keyboards.main import kb_back, kb_nginx_menu

router = Router()


class SslFSM(StatesGroup):
    email = State()


def _kb_ssl_email_skip():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏭️ Skip (use auto)", callback_data="ssl_email_skip"))
    builder.row(InlineKeyboardButton(text="⬅️ Cancel", callback_data="menu_nginx"))
    return builder.as_markup()


async def _nginx_menu_text_and_kb(cq: CallbackQuery):
    """Fetch nginx status and return (text, keyboard)."""
    try:
        st = await nginx_api.status()
        override = st.get("override", {})
        has_override = override.get("active", False)
        site_enabled = st.get("site_enabled", False)
        ovr_str = f"Custom site: {'✅ uploaded' if has_override else '❌ not uploaded'}"
        site_str = f"Site visibility: {'🟢 ON' if site_enabled else '🔴 OFF (401 stub)'}"
        text = f"🌐 <b>Nginx</b>\n{ovr_str}\n{site_str}"
        kb = kb_nginx_menu(site_enabled=site_enabled)
    except APIError as e:
        text = f"❌ {e.detail}"
        kb = kb_nginx_menu()
    return text, kb


@router.callback_query(F.data == "menu_nginx")
async def cb_nginx_menu(cq: CallbackQuery):
    text, kb = await _nginx_menu_text_and_kb(cq)
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "nginx_configure")
async def cb_nginx_configure(cq: CallbackQuery):
    await cq.answer("Configuring Nginx…")
    try:
        result = await nginx_api.configure()
        if result.get("success"):
            text = "✅ Nginx configured and reloaded"
        else:
            text = f"❌ {result.get('message', 'Failed')}"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, reply_markup=kb_back("menu_nginx"))


@router.callback_query(F.data == "nginx_ssl")
async def cb_nginx_ssl(cq: CallbackQuery, state: FSMContext):
    """Ask for optional email before issuing SSL. Default = admin@{domain}."""
    await state.set_state(SslFSM.email)
    await cq.message.answer(
        "🔒 <b>Issue SSL certificate</b>\n\n"
        "Enter your email for Let's Encrypt expiry notifications,\n"
        "or skip to use <code>admin@{your_domain}</code> automatically.",
        reply_markup=_kb_ssl_email_skip(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(SslFSM.email, F.data == "ssl_email_skip")
async def cb_ssl_skip_email(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.answer("⏳ Issuing SSL…")
    await cq.message.edit_text("⏳ <b>Issuing SSL certificate...</b>\nThis may take up to 60 seconds.", parse_mode="HTML")
    try:
        await nginx_api.ssl()
        text = "✅ <b>SSL certificate issued!</b>"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.edit_text(text, reply_markup=kb_back("menu_nginx"), parse_mode="HTML")


@router.message(SslFSM.email)
async def fsm_ssl_email(msg: Message, state: FSMContext):
    email = msg.text.strip() if msg.text else ""
    await state.clear()
    if "@" not in email:
        await msg.answer("❌ Invalid email format. Try again or go back.", reply_markup=kb_back("menu_nginx"))
        return
    await msg.answer("⏳ <b>Issuing SSL certificate...</b>\nThis may take up to 60 seconds.", parse_mode="HTML")
    try:
        await nginx_api.ssl(email=email)
        text = f"✅ <b>SSL certificate issued!</b>\nNotifications → <code>{email}</code>"
    except APIError as e:
        text = f"❌ {e.detail}"
    await msg.answer(text, reply_markup=kb_back("menu_nginx"), parse_mode="HTML")


@router.callback_query(F.data == "nginx_paths")
async def cb_nginx_paths(cq: CallbackQuery):
    try:
        paths = await nginx_api.paths()
        lines = [f"• {k}: <code>{v}</code>" for k, v in paths.items() if v]
        text = "🔒 <b>Hidden paths:</b>\n" + "\n".join(lines) if lines else "No hidden paths"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_nginx"))


@router.callback_query(F.data == "nginx_logs")
async def cb_nginx_logs(cq: CallbackQuery):
    try:
        data = await nginx_api.logs(50)
        logs = data.get("logs", "")
        text = f"📋 <b>Nginx access logs:</b>\n<pre>{logs[-2000:]}</pre>" if logs else "📋 No logs"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_nginx"))


@router.callback_query(F.data == "nginx_upload_site")
async def cb_nginx_upload_site(cq: CallbackQuery):
    await cq.message.answer(
        "📎 Send an <b>HTML file</b> or <b>ZIP archive</b> (with index.html inside).\n"
        "This will replace the default 401 auth popup.",
        parse_mode="HTML",
        reply_markup=kb_back("menu_nginx"),
    )
    await cq.answer()


@router.message(F.document)
async def handle_site_upload(msg: Message):
    doc = msg.document
    name = doc.file_name or ""
    if not (name.endswith(".html") or name.endswith(".htm") or name.endswith(".zip")):
        return  # not for us

    file = await msg.bot.get_file(doc.file_id)
    data = (await msg.bot.download_file(file.file_path)).read()
    try:
        result = await nginx_api.upload(name, data)
        ftype = result.get("type", "file")
        if ftype == "zip":
            text = f"✅ ZIP extracted ({result.get('files', 0)} files)"
        else:
            text = "✅ HTML saved"
        text += "\nNginx reloaded."
    except APIError as e:
        text = f"❌ {e.detail}"
    await msg.answer(text, reply_markup=kb_back("menu_nginx"))


@router.callback_query(F.data.in_({"nginx_site_on", "nginx_site_off"}))
async def cb_nginx_site_toggle(cq: CallbackQuery):
    enable = cq.data == "nginx_site_on"
    await cq.answer("Updating…")
    try:
        await nginx_api.site_toggle(enable)
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return
    # Refresh the menu with updated state
    text, kb = await _nginx_menu_text_and_kb(cq)
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "nginx_delete_override")
async def cb_nginx_delete_override(cq: CallbackQuery):
    try:
        await nginx_api.delete_override()
        await cq.answer("✅ Override removed")
        await cq.message.edit_text(
            "✅ Custom site removed.\nDefault 401 auth popup restored.",
            reply_markup=kb_back("menu_nginx"),
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
