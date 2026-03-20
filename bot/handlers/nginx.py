"""Nginx management — thin wrapper over /api/nginx/."""
from datetime import datetime
from html import escape

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.routers.settings_router import get_runtime
from bot.api_client import APIError, nginx_api, settings_api
from bot.keyboards.main import kb_back, kb_nginx_menu

router = Router()


class SslFSM(StatesGroup):
    email = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


def _is_nip_domain(domain: str) -> bool:
    domain = (domain or "").strip().lower().rstrip(".")
    return domain.endswith(".nip.io")


def _kb_ssl_email_skip():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_txt("⏭️ Пропустить email", "⏭️ Skip email"),
            callback_data="ssl_email_skip",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_txt("⬅️ Отмена", "⬅️ Cancel"),
            callback_data="menu_nginx",
        )
    )
    return builder.as_markup()


def _format_cert_line(cert: dict) -> str:
    if not cert or not cert.get("exists"):
        return _txt("🔐 SSL: ❌ не выпущен", "🔐 SSL: ❌ not issued")

    expires = cert.get("expires_at")
    days_left = cert.get("days_left")
    source = cert.get("source", "unknown")
    if isinstance(expires, str):
        try:
            dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if _is_ru():
                exp_human = dt.strftime("%d.%m.%Y %H:%M UTC")
                return f"🔐 SSL: ✅ до {exp_human} ({days_left} дн.), источник: {source}"
            exp_human = dt.strftime("%Y-%m-%d %H:%M UTC")
            return f"🔐 SSL: ✅ until {exp_human} ({days_left} days), source: {source}"
        except ValueError:
            pass

    return _txt(
        f"🔐 SSL: ✅ выпущен, источник: {source}",
        f"🔐 SSL: ✅ issued, source: {source}",
    )


async def _load_domain() -> str:
    try:
        data = await settings_api.get("domain")
        return (data.get("value", "") or "").strip().lower()
    except APIError:
        return ""


def _ssl_error_text(detail: str, domain: str) -> str:
    raw = (detail or "").strip()
    tail = raw[-800:] if len(raw) > 800 else raw
    safe_tail = escape(tail)

    if "Some challenges have failed" in raw or "unauthorized" in raw.lower():
        if _is_ru():
            return (
                "❌ <b>Проверка домена не прошла.</b>\n"
                f"Домен: <code>{escape(domain)}</code>\n\n"
                "Проверьте:\n"
                "1) DNS A-запись домена указывает на этот сервер\n"
                "2) порт 80 открыт и доступен из интернета\n"
                "3) в Nginx применена актуальная конфигурация\n\n"
                f"<pre>{safe_tail}</pre>"
            )
        return (
            "❌ <b>Domain validation failed.</b>\n"
            f"Domain: <code>{escape(domain)}</code>\n\n"
            "Check:\n"
            "1) domain A-record points to this server\n"
            "2) port 80 is reachable from the internet\n"
            "3) Nginx config was applied before issuing cert\n\n"
            f"<pre>{safe_tail}</pre>"
        )

    return _txt(
        f"❌ <b>Ошибка выпуска SSL</b>\n<pre>{safe_tail}</pre>",
        f"❌ <b>SSL issuing failed</b>\n<pre>{safe_tail}</pre>",
    )


async def _issue_ssl(reply_target: Message, email: str | None = None, domain: str | None = None):
    domain = (domain or await _load_domain()).strip().lower()
    if not domain:
        await reply_target.answer(
            _txt(
                "❌ Домен не настроен. Сначала задайте его в Настройках.",
                "❌ Domain is not configured. Set it in Settings first.",
            ),
            reply_markup=kb_back("menu_nginx"),
        )
        return

    wait_text = _txt(
        "⏳ <b>Выпускаю SSL сертификат...</b>\nЭто может занять до 60 секунд.",
        "⏳ <b>Issuing SSL certificate...</b>\nThis may take up to 60 seconds.",
    )
    progress_msg = await reply_target.answer(wait_text, parse_mode="HTML")

    try:
        await nginx_api.ssl(email=email or "")
        if email:
            result = _txt(
                f"✅ <b>SSL выпущен</b>\nДомен: <code>{escape(domain)}</code>\nEmail: <code>{escape(email)}</code>",
                f"✅ <b>SSL issued</b>\nDomain: <code>{escape(domain)}</code>\nEmail: <code>{escape(email)}</code>",
            )
        else:
            result = _txt(
                f"✅ <b>SSL выпущен</b>\nДомен: <code>{escape(domain)}</code>\nБез email (как вы выбрали).",
                f"✅ <b>SSL issued</b>\nDomain: <code>{escape(domain)}</code>\nNo email (as requested).",
            )
    except APIError as e:
        result = _ssl_error_text(e.detail, domain)

    await progress_msg.edit_text(result, parse_mode="HTML", reply_markup=kb_back("menu_nginx"))


async def _nginx_menu_text_and_kb():
    """Fetch nginx status and return (text, keyboard)."""
    try:
        st = await nginx_api.status()
        override = st.get("override", {})
        has_override = override.get("active", False)
        site_enabled = st.get("site_enabled", False)
        domain = (st.get("domain") or "").strip()
        cert = st.get("cert") or {}

        domain_line = _txt(
            f"🌍 Домен: <code>{escape(domain or '—')}</code>",
            f"🌍 Domain: <code>{escape(domain or '—')}</code>",
        )
        cert_line = _format_cert_line(cert)
        override_line = _txt(
            f"📄 Публичная страница: {'✅ загружена' if has_override else '❌ не загружена'}",
            f"📄 Public page files: {'✅ uploaded' if has_override else '❌ not uploaded'}",
        )
        site_line = _txt(
            f"👁 Публичная страница: {'🟢 включена' if site_enabled else '🔴 выключена (на / 401 заглушка)'}",
            f"👁 Public page: {'🟢 ON' if site_enabled else '🔴 OFF (401 stub on /)'}",
        )
        text = "\n".join([
            "🌐 <b>Nginx</b>",
            domain_line,
            cert_line,
            override_line,
            site_line,
        ])
        kb = kb_nginx_menu(site_enabled=site_enabled)
    except APIError as e:
        text = f"❌ {escape(e.detail)}"
        kb = kb_nginx_menu()
    return text, kb


@router.callback_query(F.data == "menu_nginx")
async def cb_nginx_menu(cq: CallbackQuery):
    text, kb = await _nginx_menu_text_and_kb()
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "nginx_configure")
async def cb_nginx_configure(cq: CallbackQuery):
    await cq.answer(_txt("Настраиваю Nginx…", "Configuring Nginx…"))
    try:
        result = await nginx_api.configure()
        if result.get("success"):
            text = _txt("✅ Nginx настроен и перезагружен", "✅ Nginx configured and reloaded")
        else:
            text = f"❌ {result.get('message', _txt('Ошибка', 'Failed'))}"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, reply_markup=kb_back("menu_nginx"))


@router.callback_query(F.data == "nginx_ssl")
async def cb_nginx_ssl(cq: CallbackQuery, state: FSMContext):
    """
    For nip.io domains we skip email prompt and issue immediately.
    For custom domains we ask optional email.
    """
    domain = await _load_domain()
    if not domain:
        await cq.answer(_txt("Сначала задайте домен", "Set domain first"), show_alert=True)
        await cq.message.answer(
            _txt(
                "❌ Домен не настроен. Откройте: ⚙️ Настройки → Домен.",
                "❌ Domain is not configured. Open: ⚙️ Settings → Domain.",
            ),
            reply_markup=kb_back("menu_nginx"),
        )
        return

    if _is_nip_domain(domain):
        await state.clear()
        await cq.answer(_txt("Выпускаю SSL…", "Issuing SSL…"))
        await _issue_ssl(cq.message, email=None, domain=domain)
        return

    await state.set_state(SslFSM.email)
    await cq.message.answer(
        _txt(
            "🔒 <b>Выпуск SSL-сертификата</b>\n\n"
            f"Домен: <code>{escape(domain)}</code>\n"
            "Введите email для уведомлений Let's Encrypt,\n"
            "или нажмите «Пропустить» для выпуска без email.",
            "🔒 <b>Issue SSL certificate</b>\n\n"
            f"Domain: <code>{escape(domain)}</code>\n"
            "Enter email for Let's Encrypt expiry notifications,\n"
            "or press Skip to issue without email.",
        ),
        reply_markup=_kb_ssl_email_skip(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(SslFSM.email, F.data == "ssl_email_skip")
async def cb_ssl_skip_email(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.answer(_txt("Выпускаю SSL…", "Issuing SSL…"))
    await _issue_ssl(cq.message, email=None)


@router.message(SslFSM.email)
async def fsm_ssl_email(msg: Message, state: FSMContext):
    email = msg.text.strip() if msg.text else ""
    if "@" not in email:
        await msg.answer(
            _txt("❌ Неверный формат email. Попробуйте снова.", "❌ Invalid email format. Try again."),
            reply_markup=kb_back("menu_nginx"),
        )
        return

    await state.clear()
    await _issue_ssl(msg, email=email)


@router.callback_query(F.data == "nginx_paths")
async def cb_nginx_paths(cq: CallbackQuery):
    try:
        paths = await nginx_api.paths()
        lines = [f"• {k}: <code>{v}</code>" for k, v in paths.items() if v]
        text = (
            "🔒 <b>Скрытые пути:</b>\n" + "\n".join(lines)
            if lines
            else _txt("Скрытых путей нет", "No hidden paths")
        )
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_nginx"))


@router.callback_query(F.data == "nginx_logs")
async def cb_nginx_logs(cq: CallbackQuery):
    try:
        data = await nginx_api.logs(50)
        logs = data.get("logs", "")
        text = (
            f"📋 <b>{_txt('Логи доступа Nginx', 'Nginx access logs')}:</b>\n<pre>{escape(logs[-2000:])}</pre>"
            if logs
            else _txt("📋 Логи пусты", "📋 No logs")
        )
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_nginx"))


@router.callback_query(F.data == "nginx_upload_site")
async def cb_nginx_upload_site(cq: CallbackQuery):
    await cq.message.answer(
        _txt(
            "📎 Отправьте <b>HTML файл</b> или <b>ZIP архив</b> (внутри должен быть index.html).\n"
            "Это контент публичной страницы на <code>/</code>.\n"
            "Web UI <code>/web/</code> не затрагивается.",
            "📎 Send an <b>HTML file</b> or <b>ZIP archive</b> (with index.html inside).\n"
            "This is content for the public page on <code>/</code>.\n"
            "Web UI <code>/web/</code> is not affected.",
        ),
        parse_mode="HTML",
        reply_markup=kb_back("menu_nginx"),
    )
    await cq.answer()


@router.message(StateFilter(None), F.document)
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
            text = _txt(
                f"✅ ZIP распакован ({result.get('files', 0)} файлов)\nNginx перезагружен.",
                f"✅ ZIP extracted ({result.get('files', 0)} files)\nNginx reloaded.",
            )
        else:
            text = _txt("✅ HTML сохранён\nNginx перезагружен.", "✅ HTML saved\nNginx reloaded.")
    except APIError as e:
        text = f"❌ {e.detail}"
    await msg.answer(text, reply_markup=kb_back("menu_nginx"))


@router.callback_query(F.data.in_({"nginx_site_on", "nginx_site_off"}))
async def cb_nginx_site_toggle(cq: CallbackQuery):
    enable = cq.data == "nginx_site_on"
    await cq.answer(_txt("Обновляю…", "Updating…"))
    try:
        await nginx_api.site_toggle(enable)
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return
    text, kb = await _nginx_menu_text_and_kb()
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "nginx_delete_override")
async def cb_nginx_delete_override(cq: CallbackQuery):
    try:
        await nginx_api.delete_override()
        await cq.answer(_txt("✅ Страница удалена", "✅ Page files removed"))
        await cq.message.edit_text(
            _txt(
                "✅ Файлы публичной страницы удалены.\nВозвращена стандартная 401-заглушка на <code>/</code>.",
                "✅ Public page files removed.\nDefault 401 auth popup restored on <code>/</code>.",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("menu_nginx"),
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
