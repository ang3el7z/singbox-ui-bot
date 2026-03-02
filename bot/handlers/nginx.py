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

MAX_UPLOAD_MB = 20  # max ZIP size


class NginxFSM(StatesGroup):
    waiting_site_file = State()   # HTML or ZIP


# ─── Menu ─────────────────────────────────────────────────────────────────────

def nginx_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("nginx_configure"), callback_data="nginx:configure"),
        InlineKeyboardButton(text=t("nginx_ssl"),       callback_data="nginx:ssl"),
    )
    builder.row(
        InlineKeyboardButton(text="🎨 Сайт-заглушка",   callback_data="nginx:override_menu"),
        InlineKeyboardButton(text=t("nginx_logs"),       callback_data="nginx:logs"),
    )
    builder.row(
        InlineKeyboardButton(text="🔗 Скрытые пути",    callback_data="nginx:paths"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:nginx")
async def cb_nginx_menu(callback: CallbackQuery) -> None:
    from bot.config import settings
    domain = settings.domain or "не настроен"
    status = nginx_service.override_status()
    stub_line = "🎨 Заглушка: ✅ активна" if status["active"] else "🎨 Заглушка: 🔒 auth-попап (по умолчанию)"
    await callback.message.edit_text(
        f"🌐 <b>Nginx</b>\n\n▪ Домен: <code>{domain}</code>\n▪ {stub_line}",
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
        nginx_service.ensure_htpasswd()
        config_text = nginx_service.generate_config(domain=settings.domain)
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
                f"⚠️ Конфиг записан, reload завершился с предупреждением:\n<code>{truncate(msg, 800)}</code>",
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
        await callback.message.edit_text(t("nginx_ssl_issued"), reply_markup=back_kb("menu:nginx"))
    else:
        await callback.message.edit_text(
            f"❌ Ошибка получения сертификата:\n<code>{truncate(output, 1500)}</code>",
            reply_markup=back_kb("menu:nginx"),
            parse_mode="HTML",
        )


# ─── Override site menu ───────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:override_menu")
async def cb_nginx_override_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    status = nginx_service.override_status()

    if status["active"]:
        files_preview = ", ".join(status["files"][:6])
        if len(status["files"]) > 6:
            files_preview += f" и ещё {len(status['files']) - 6}…"
        text = (
            f"🎨 <b>Сайт-заглушка</b>\n\n"
            f"▪ Статус: ✅ активна\n"
            f"▪ Файлов: {len(status['files'])} ({status['size_kb']} КБ)\n"
            f"▪ Состав: <code>{files_preview}</code>\n\n"
            f"Загрузите новый файл чтобы заменить, или удалите чтобы вернуть 🔒 auth-попап."
        )
    else:
        text = (
            f"🎨 <b>Сайт-заглушка</b>\n\n"
            f"▪ Статус: 🔒 auth-попап (по умолчанию)\n\n"
            f"Посетители видят браузерное окно авторизации (HTTP 401 Basic Auth).\n"
            f"Сервер выглядит как защищённый ресурс — настоящий адрес скрыт.\n\n"
            f"<i>Чтобы показать свой сайт — загрузите HTML-файл или ZIP-архив.</i>"
        )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📄 Загрузить HTML / ZIP", callback_data="nginx:override_upload"),
    )
    if status["active"]:
        builder.row(
            InlineKeyboardButton(text="🗑 Удалить (вернуть auth-попап)", callback_data="nginx:override_delete"),
        )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:nginx"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ─── Upload site ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:override_upload")
async def cb_nginx_override_upload(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(NginxFSM.waiting_site_file)
    await callback.message.answer(
        "📤 <b>Загрузка сайта-заглушки</b>\n\n"
        "Отправьте один из вариантов:\n"
        "• <b>HTML-файл</b> — одностраничный сайт (index.html)\n"
        "• <b>ZIP-архив</b> — полный сайт с CSS, изображениями и т.д.\n\n"
        "⚠️ Максимальный размер: <b>20 МБ</b>\n"
        "⚠️ В ZIP-архиве должен быть <code>index.html</code>\n\n"
        "<i>Статические ресурсы (CSS/JS/картинки) доступны по пути <code>/override/имя_файла</code></i>",
        reply_markup=back_kb("nginx:override_menu"),
        parse_mode="HTML",
    )


@router.message(NginxFSM.waiting_site_file, F.document)
async def fsm_nginx_site_file(message: Message, state: FSMContext) -> None:
    await state.clear()
    doc: Document = message.document
    filename = doc.file_name or ""

    # Size check
    if doc.file_size and doc.file_size > MAX_UPLOAD_MB * 1024 * 1024:
        await message.answer(f"❌ Файл слишком большой. Максимум {MAX_UPLOAD_MB} МБ.")
        return

    is_html = filename.lower().endswith((".html", ".htm"))
    is_zip  = filename.lower().endswith(".zip")

    if not is_html and not is_zip:
        await message.answer(
            "❌ Неподдерживаемый формат. Загрузите <b>.html</b> или <b>.zip</b> файл.",
            parse_mode="HTML",
            reply_markup=back_kb("nginx:override_menu"),
        )
        return

    await message.answer("⏳ Загружаю файл...")

    try:
        import io
        bot = message.bot
        file = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)
        content = buf.getvalue()

        if is_html:
            nginx_service.save_override_html(content)
            await log_action(message.from_user.id, "nginx_override_html", filename)
            await message.answer(
                "✅ <b>HTML-файл сохранён.</b>\n\n"
                "Теперь посетители будут видеть вашу страницу вместо auth-попапа.\n"
                "Нажмите <b>⚙️ Настроить</b> в меню Nginx чтобы перезагрузить конфиг.",
                parse_mode="HTML",
                reply_markup=back_kb("nginx:override_menu"),
            )
        else:
            count = nginx_service.save_override_zip(content)
            if not (nginx_service.OVERRIDE_DIR / "index.html").exists():
                await message.answer(
                    "❌ В архиве не найден <code>index.html</code>. Убедитесь что файл есть в корне архива.",
                    parse_mode="HTML",
                    reply_markup=back_kb("nginx:override_menu"),
                )
                nginx_service.remove_override()
                return
            await log_action(message.from_user.id, "nginx_override_zip", f"{filename} ({count} файлов)")
            await message.answer(
                f"✅ <b>ZIP-архив распакован:</b> {count} файлов\n\n"
                "Нажмите <b>⚙️ Настроить</b> в меню Nginx чтобы перезагрузить конфиг.",
                parse_mode="HTML",
                reply_markup=back_kb("nginx:override_menu"),
            )

        # Auto-reload nginx after upload
        ok, _ = await nginx_service.reload_nginx()
        if ok:
            await message.answer("🔄 Nginx перезагружен автоматически.")

    except Exception as e:
        await message.answer(t("error", msg=str(e)), reply_markup=back_kb("nginx:override_menu"))


@router.message(NginxFSM.waiting_site_file)
async def fsm_nginx_site_file_wrong(message: Message, state: FSMContext) -> None:
    await message.answer("Пожалуйста, отправьте файл (HTML или ZIP).")


# ─── Delete override ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:override_delete")
async def cb_nginx_override_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    nginx_service.remove_override()
    await nginx_service.reload_nginx()
    await log_action(callback.from_user.id, "nginx_override_delete")
    await callback.message.edit_text(
        "✅ Сайт-заглушка удалена.\n\nТеперь посетители снова видят 🔒 auth-попап.",
        reply_markup=back_kb("menu:nginx"),
    )


# ─── Hidden paths ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "nginx:paths")
async def cb_nginx_paths(callback: CallbackQuery) -> None:
    await callback.answer()
    paths = nginx_service.get_hidden_paths()
    text = "🔗 <b>Скрытые пути доступа</b>\n\n"
    labels = {
        "panel":          "🖥 Панель управления (s-ui)",
        "subscriptions":  "📋 Подписки",
        "adguard":        "🛡 AdGuard Home",
        "federation_api": "🔗 Federation API",
    }
    for key, url in paths.items():
        text += f"{labels.get(key, key)}:\n<code>{url}</code>\n\n"
    text += "<i>Пути скрыты хэшем SECRET_KEY. Не передавайте их третьим лицам.</i>"
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
