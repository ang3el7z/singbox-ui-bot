from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, Document
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services import nginx_service
from bot.keyboards.main import back_kb
from bot.texts import t
from bot.utils import truncate
from bot.middleware.auth import log_action

router = Router()

# Saved in memory between restarts; persisted via re-reading .env or bot settings
_current_stub_mode: str = "auth"


def _get_stub_mode() -> str:
    return _current_stub_mode


def _set_stub_mode(mode: str) -> None:
    global _current_stub_mode
    _current_stub_mode = mode


class NginxFSM(StatesGroup):
    waiting_custom_html = State()
    waiting_auth_realm  = State()


# ─── Menu ─────────────────────────────────────────────────────────────────────

def nginx_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("nginx_configure"), callback_data="nginx:configure"),
        InlineKeyboardButton(text=t("nginx_ssl"),       callback_data="nginx:ssl"),
    )
    builder.row(
        InlineKeyboardButton(text="🎭 Заглушка",        callback_data="nginx:stub"),
        InlineKeyboardButton(text=t("nginx_logs"),      callback_data="nginx:logs"),
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Скрытые пути",    callback_data="nginx:paths"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:nginx")
async def cb_nginx_menu(callback: CallbackQuery) -> None:
    from bot.config import settings
    domain  = settings.domain or "не настроен"
    mode    = _get_stub_mode()
    mode_lbl = nginx_service.STUB_MODES.get(mode, mode)
    await callback.message.edit_text(
        f"🌐 <b>Nginx</b>\n\n"
        f"▪ Домен: <code>{domain}</code>\n"
        f"▪ Заглушка: {mode_lbl}",
        reply_markup=nginx_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Apply / configure ────────────────────────────────────────────────────────

async def _apply_config(stub_mode: str, auth_realm: str = "Protected Area") -> tuple[bool, str]:
    from bot.config import settings
    config_text = nginx_service.generate_config(
        domain=settings.domain,
        stub_mode=stub_mode,
        auth_realm=auth_realm,
    )
    nginx_service.write_config(config_text)
    ok, msg = await nginx_service.test_nginx_config()
    if not ok:
        return False, msg
    ok, msg = await nginx_service.reload_nginx()
    return ok, msg


@router.callback_query(F.data == "nginx:configure")
async def cb_nginx_configure(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        ok, msg = await _apply_config(_get_stub_mode())
        await log_action(callback.from_user.id, "nginx_configure")
        if ok:
            await callback.message.edit_text(
                t("nginx_configured"),
                reply_markup=back_kb("menu:nginx"),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                f"❌ Ошибка конфигурации:\n<code>{truncate(msg, 1200)}</code>",
                reply_markup=back_kb("menu:nginx"),
                parse_mode="HTML",
            )
    except Exception as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:nginx"))


# ─── SSL ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:ssl")
async def cb_nginx_ssl(callback: CallbackQuery) -> None:
    await callback.answer()
    from bot.config import settings
    if not settings.domain or not settings.email:
        await callback.message.edit_text(
            "❌ Домен и email не настроены в .env (DOMAIN, EMAIL)",
            reply_markup=back_kb("menu:nginx"),
        )
        return
    await callback.message.edit_text(
        f"⏳ Получение SSL сертификата для <b>{settings.domain}</b>...",
        parse_mode="HTML",
    )
    ok, output = await nginx_service.issue_ssl_cert(settings.domain, settings.email)
    await log_action(callback.from_user.id, "nginx_ssl", f"ok={ok}")
    if ok:
        await callback.message.edit_text(t("nginx_ssl_issued"), reply_markup=back_kb("menu:nginx"))
    else:
        await callback.message.edit_text(
            f"❌ Ошибка:\n<code>{truncate(output, 1500)}</code>",
            reply_markup=back_kb("menu:nginx"),
            parse_mode="HTML",
        )


# ─── Stub site ────────────────────────────────────────────────────────────────

def stub_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    current = _get_stub_mode()
    for mode_key, mode_label in nginx_service.STUB_MODES.items():
        # Skip custom if no file uploaded yet
        if mode_key == "custom" and not nginx_service.has_custom_stub():
            builder.row(InlineKeyboardButton(
                text="📁 Загрузить свой HTML",
                callback_data="nginx:stub:upload",
            ))
            continue
        marker = "✅ " if mode_key == current else ""
        builder.row(InlineKeyboardButton(
            text=f"{marker}{mode_label}",
            callback_data=f"nginx:stub:set:{mode_key}",
        ))
    if nginx_service.has_custom_stub():
        builder.row(InlineKeyboardButton(
            text="📁 Заменить HTML",
            callback_data="nginx:stub:upload",
        ))
    builder.row(InlineKeyboardButton(
        text="✏️ Изменить заголовок диалога",
        callback_data="nginx:stub:realm",
    ))
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:nginx"))
    return builder.as_markup()


@router.callback_query(F.data == "nginx:stub")
async def cb_nginx_stub(callback: CallbackQuery) -> None:
    await callback.answer()
    current_mode  = _get_stub_mode()
    current_label = nginx_service.STUB_MODES.get(current_mode, current_mode)
    has_custom    = nginx_service.has_custom_stub()

    text = (
        f"🎭 <b>Настройка заглушки</b>\n\n"
        f"▪ Текущий режим: <b>{current_label}</b>\n\n"
        f"<b>auth</b> — браузер показывает нативное окно авторизации (401). "
        f"Выглядит как защищённый сервер.\n\n"
        f"<b>custom</b> — ваша HTML страница.\n\n"
        f"<b>none</b> — возвращать 404."
    )
    if current_mode == "auth":
        text += "\n\n💡 <i>Никаких файлов HTML не нужно — браузер сам покажет окно входа.</i>"
    if has_custom and current_mode == "custom":
        text += "\n\n✅ <i>Ваш HTML файл загружен.</i>"

    await callback.message.edit_text(text, reply_markup=stub_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("nginx:stub:set:"))
async def cb_nginx_stub_set(callback: CallbackQuery) -> None:
    await callback.answer()
    mode = callback.data.split(":")[3]

    if mode == "custom" and not nginx_service.has_custom_stub():
        await callback.answer("Сначала загрузите HTML файл.", show_alert=True)
        return

    _set_stub_mode(mode)
    ok, msg = await _apply_config(mode)
    await log_action(callback.from_user.id, "nginx_stub_mode", f"mode={mode}")
    label = nginx_service.STUB_MODES.get(mode, mode)
    if ok:
        await callback.message.edit_text(
            f"✅ Режим заглушки изменён: <b>{label}</b>",
            reply_markup=back_kb("menu:nginx"),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"⚠️ Режим изменён, но reload nginx завершился с предупреждением:\n<code>{truncate(msg, 800)}</code>",
            reply_markup=back_kb("menu:nginx"),
            parse_mode="HTML",
        )


# ─── Upload custom HTML ───────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:stub:upload")
async def cb_nginx_stub_upload(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(NginxFSM.waiting_custom_html)
    await callback.message.answer(
        "📁 Отправьте <b>.html</b> файл.\n\n"
        "После загрузки автоматически переключу режим заглушки на <b>custom</b> и применю конфиг.",
        reply_markup=back_kb("nginx:stub"),
        parse_mode="HTML",
    )


@router.message(NginxFSM.waiting_custom_html, F.document)
async def fsm_nginx_custom_html(message: Message, state: FSMContext) -> None:
    await state.clear()
    doc: Document = message.document
    if not (doc.file_name or "").lower().endswith((".html", ".htm")):
        await message.answer("Пожалуйста, загрузите файл с расширением .html или .htm")
        return
    try:
        import io
        file = await message.bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await message.bot.download_file(file.file_path, buf)
        nginx_service.save_custom_stub(buf.getvalue())

        _set_stub_mode("custom")
        ok, msg = await _apply_config("custom")
        await log_action(message.from_user.id, "nginx_upload_stub")

        if ok:
            await message.answer(
                "✅ HTML загружен, режим заглушки переключён на <b>custom</b> и конфиг применён.",
                reply_markup=back_kb("menu:nginx"),
                parse_mode="HTML",
            )
        else:
            await message.answer(
                f"✅ HTML загружен, но reload nginx завершился с предупреждением:\n<code>{truncate(msg, 800)}</code>",
                reply_markup=back_kb("menu:nginx"),
                parse_mode="HTML",
            )
    except Exception as e:
        await message.answer(t("error", msg=str(e)))


# ─── Change auth realm label ─────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:stub:realm")
async def cb_nginx_stub_realm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(NginxFSM.waiting_auth_realm)
    await callback.message.answer(
        "✏️ Введите текст заголовка окна авторизации.\n\n"
        "Например: <code>Private Area</code>, <code>Company Portal</code>, <code>Restricted</code>\n\n"
        "<i>Это текст, который браузер отобразит в диалоге ввода логина/пароля.</i>",
        reply_markup=back_kb("nginx:stub"),
        parse_mode="HTML",
    )


@router.message(NginxFSM.waiting_auth_realm)
async def fsm_nginx_auth_realm(message: Message, state: FSMContext) -> None:
    await state.clear()
    realm = message.text.strip()
    if not realm:
        await message.answer("Заголовок не может быть пустым.")
        return
    try:
        ok, msg = await _apply_config(_get_stub_mode(), auth_realm=realm)
        await log_action(message.from_user.id, "nginx_auth_realm", realm)
        if ok:
            await message.answer(
                f"✅ Заголовок изменён на: <b>{realm}</b>",
                reply_markup=back_kb("nginx:stub"),
                parse_mode="HTML",
            )
        else:
            await message.answer(
                f"⚠️ Заголовок изменён, но reload завершился с предупреждением:\n<code>{truncate(msg, 600)}</code>",
                reply_markup=back_kb("menu:nginx"),
                parse_mode="HTML",
            )
    except Exception as e:
        await message.answer(t("error", msg=str(e)))


# ─── Paths ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:paths")
async def cb_nginx_paths(callback: CallbackQuery) -> None:
    await callback.answer()
    paths = nginx_service.get_hidden_paths()
    labels = {
        "panel":          "🖥 Панель управления",
        "subscriptions":  "📋 Подписки",
        "adguard":        "🛡 AdGuard Home",
        "federation_api": "🔗 Federation API",
    }
    text = "🔗 <b>Скрытые пути доступа</b>\n\n"
    for key, url in paths.items():
        text += f"{labels.get(key, key)}:\n<code>{url}</code>\n\n"
    text += "<i>Пути скрыты хэшем секретного ключа. Не передавайте их третьим лицам.</i>"
    await callback.message.edit_text(text, reply_markup=back_kb("menu:nginx"), parse_mode="HTML")


# ─── Access logs ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:logs")
async def cb_nginx_logs(callback: CallbackQuery) -> None:
    await callback.answer()
    logs = await nginx_service.get_access_logs(lines=40)
    text = f"📜 <b>Nginx Access Log</b>\n\n<code>{truncate(logs, 3000)}</code>"
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("refresh"), callback_data="nginx:logs"),
        InlineKeyboardButton(text=t("back"),    callback_data="menu:nginx"),
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
