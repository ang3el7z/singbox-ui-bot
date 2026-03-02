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


class NginxFSM(StatesGroup):
    waiting_custom_stub = State()


# ─── Menu ─────────────────────────────────────────────────────────────────────

def nginx_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("nginx_configure"), callback_data="nginx:configure"),
        InlineKeyboardButton(text=t("nginx_ssl"), callback_data="nginx:ssl"),
    )
    builder.row(
        InlineKeyboardButton(text=t("nginx_stub"), callback_data="nginx:stub"),
        InlineKeyboardButton(text=t("nginx_logs"), callback_data="nginx:logs"),
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Скрытые пути", callback_data="nginx:paths"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:nginx")
async def cb_nginx_menu(callback: CallbackQuery) -> None:
    from bot.config import settings
    domain = settings.domain or "не настроен"
    await callback.message.edit_text(
        f"🌐 <b>Nginx</b>\n\n▪ Домен: <code>{domain}</code>",
        reply_markup=nginx_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ─── Configure ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:configure")
async def cb_nginx_configure(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        from bot.config import settings
        config_text = nginx_service.generate_config(
            domain=settings.domain,
            stub_theme=settings.stub_theme,
        )
        nginx_service.write_config(config_text)
        ok, msg = await nginx_service.test_nginx_config()
        if not ok:
            await callback.message.edit_text(
                f"❌ Конфиг содержит ошибки:\n<code>{truncate(msg, 1000)}</code>",
                reply_markup=back_kb("menu:nginx"),
                parse_mode="HTML",
            )
            return
        ok, msg = await nginx_service.reload_nginx()
        await log_action(callback.from_user.id, "nginx_configure")
        if ok:
            await callback.message.edit_text(
                t("nginx_configured"),
                reply_markup=back_kb("menu:nginx"),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                f"⚠️ Конфиг записан, но reload завершился с предупреждением:\n<code>{truncate(msg, 800)}</code>",
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
    await log_action(callback.from_user.id, "nginx_ssl", f"domain={settings.domain} ok={ok}")
    if ok:
        await callback.message.edit_text(
            t("nginx_ssl_issued"),
            reply_markup=back_kb("menu:nginx"),
        )
    else:
        await callback.message.edit_text(
            f"❌ Ошибка получения сертификата:\n<code>{truncate(output, 1500)}</code>",
            reply_markup=back_kb("menu:nginx"),
            parse_mode="HTML",
        )


# ─── Stub site ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:stub")
async def cb_nginx_stub(callback: CallbackQuery) -> None:
    await callback.answer()
    themes = nginx_service.list_stub_themes()
    from bot.config import settings
    current = settings.stub_theme

    builder = InlineKeyboardBuilder()
    for theme_key, theme_label in themes.items():
        marker = "✅ " if theme_key == current else ""
        builder.row(InlineKeyboardButton(
            text=f"{marker}{theme_label}",
            callback_data=f"nginx:stub:set:{theme_key}",
        ))
    builder.row(InlineKeyboardButton(text="📁 Загрузить HTML", callback_data="nginx:stub:upload"))
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:nginx"))
    await callback.message.edit_text(
        t("select_stub_theme"),
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("nginx:stub:set:"))
async def cb_nginx_stub_set(callback: CallbackQuery) -> None:
    await callback.answer()
    theme = callback.data.split(":")[3]
    from bot.config import settings
    # Regenerate config with new stub theme
    config_text = nginx_service.generate_config(stub_theme=theme)
    nginx_service.write_config(config_text)
    await nginx_service.reload_nginx()
    await log_action(callback.from_user.id, "nginx_stub_theme", f"theme={theme}")
    await callback.message.edit_text(
        f"✅ Тема сайта-заглушки изменена на <b>{nginx_service.STUB_THEMES.get(theme, theme)}</b>",
        reply_markup=back_kb("menu:nginx"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "nginx:stub:upload")
async def cb_nginx_stub_upload(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(NginxFSM.waiting_custom_stub)
    await callback.message.answer(
        "📁 Отправьте HTML файл для кастомной заглушки.\n<i>Файл будет сохранён как index.html в теме 'custom'</i>",
        reply_markup=back_kb("nginx:stub"),
        parse_mode="HTML",
    )


@router.message(NginxFSM.waiting_custom_stub, F.document)
async def fsm_nginx_stub_file(message: Message, state: FSMContext) -> None:
    await state.clear()
    doc: Document = message.document
    if not (doc.file_name.endswith(".html") or doc.file_name.endswith(".htm")):
        await message.answer("Пожалуйста, загрузите .html файл.")
        return
    try:
        from pathlib import Path
        from aiogram import Bot
        import io
        bot: Bot = message.bot
        file = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)
        custom_dir = nginx_service.STUBS_DIR / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        (custom_dir / "index.html").write_bytes(buf.getvalue())
        await log_action(message.from_user.id, "nginx_upload_stub")
        await message.answer(
            "✅ Кастомная заглушка загружена. Выберите тему 'custom' для применения.",
            reply_markup=back_kb("nginx:stub"),
        )
    except Exception as e:
        await message.answer(t("error", msg=str(e)))


# ─── Paths ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:paths")
async def cb_nginx_paths(callback: CallbackQuery) -> None:
    await callback.answer()
    paths = nginx_service.get_hidden_paths()
    text = "🔗 <b>Скрытые пути доступа</b>\n\n"
    labels = {
        "panel": "🖥 Панель управления",
        "subscriptions": "📋 Подписки",
        "adguard": "🛡 AdGuard Home",
        "federation_api": "🔗 Federation API",
    }
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
        InlineKeyboardButton(text=t("back"), callback_data="menu:nginx"),
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
