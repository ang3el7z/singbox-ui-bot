"""
Maintenance section: backup, restore, IP ban, log management.
"""
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.routers.settings_router import get_runtime
from bot.api_client import APIError, maintenance_api
from bot.keyboards.main import kb_back

router = Router()

_BACKUP_INTERVALS = [
    ("🚫 Off", 0),
    ("6 hours", 6),
    ("12 hours", 12),
    ("24 hours", 24),
    ("48 hours", 48),
    ("7 days", 168),
]

_CLEAN_INTERVALS = [
    ("🚫 Off", 0),
    ("24 hours", 24),
    ("3 days", 72),
    ("7 days", 168),
    ("30 days", 720),
]


class IpBanFSM(StatesGroup):
    manual_ip = State()


class RestoreFSM(StatesGroup):
    archive = State()
    confirm = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


def _pick_localized_notes(git: dict, lang: str) -> str:
    raw = (git.get("latest_tag_notes") or "").strip()
    localized = git.get("latest_tag_notes_i18n") or {}
    if not isinstance(localized, dict) or not localized:
        return raw

    lang_norm = (lang or "en").strip().lower()
    base_lang = lang_norm.split("-", 1)[0]
    en = (localized.get("en") or "").strip()

    for key in (lang_norm, base_lang):
        text = (localized.get(key) or "").strip()
        if text:
            return text
    if en:
        return en

    for value in localized.values():
        text = (value or "").strip()
        if text:
            return text
    return raw


async def _send_preflight_backup(cq: CallbackQuery, *, reason_ru: str, reason_en: str) -> str | None:
    try:
        pkg = await maintenance_api.backup_download_package()
        payload = pkg.get("content") or b""
        backup_path = (pkg.get("backup_path") or "").strip()
        from datetime import datetime

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        archive = BufferedInputFile(payload, filename=f"backup_{ts}.zip")
        caption = _txt(f"Backup before {reason_ru}", f"Backup before {reason_en}")
        await cq.message.answer_document(archive, caption=caption, parse_mode="HTML")
        if not backup_path:
            await cq.message.answer(
                _txt("Cannot detect backup path on server.", "Cannot detect backup path on server."),
                reply_markup=kb_back("maint_update_menu"),
            )
            return None
        return backup_path
    except APIError as exc:
        await cq.message.answer(
            _txt(
                f"Failed to prepare backup: <code>{escape(exc.detail)}</code>",
                f"Failed to prepare backup: <code>{escape(exc.detail)}</code>",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("maint_update_menu"),
        )
        return None
    except Exception as exc:
        await cq.message.answer(
            _txt(
                f"Failed to prepare backup: <code>{escape(str(exc))}</code>",
                f"Failed to prepare backup: <code>{escape(str(exc))}</code>",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("maint_update_menu"),
        )
        return None


def _kb_main(status: dict) -> InlineKeyboardMarkup:
    b_hours = status.get("backup", {}).get("auto_hours", 0)
    c_hours = status.get("logs", {}).get("auto_clean_hours", 0)
    ban_cnt = status.get("ip_ban", {}).get("count", 0)

    b_label = f"{'🔄' if b_hours else '⏸'} Backup: {'every ' + str(b_hours) + 'h' if b_hours else 'off'}"
    c_label = f"{'🧹' if c_hours else '⏸'} Log clean: {'every ' + str(c_hours) + 'h' if c_hours else 'off'}"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💾 Backup now", callback_data="maint_backup_now"),
        InlineKeyboardButton(text="♻️ Restore ZIP", callback_data="maint_restore_zip"),
    )
    builder.row(InlineKeyboardButton(text=b_label, callback_data="maint_backup_interval"))
    builder.row(InlineKeyboardButton(text="📋 Logs", callback_data="maint_logs_menu"))
    builder.row(InlineKeyboardButton(text=c_label, callback_data="maint_clean_interval"))
    builder.row(InlineKeyboardButton(text=f"🚫 IP Ban ({ban_cnt})", callback_data="maint_ipban_menu"))
    builder.row(InlineKeyboardButton(text="🪟 Windows Service", callback_data="maint_windows"))
    builder.row(InlineKeyboardButton(text=_txt("⬆️ Обновления", "⬆️ Updates"), callback_data="maint_update_menu"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu"))
    return builder.as_markup()


def _kb_intervals(items: list, prefix: str, current: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, hours in items:
        tick = "✅ " if hours == current else ""
        builder.row(InlineKeyboardButton(text=f"{tick}{label}", callback_data=f"{prefix}_{hours}"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu_maintenance"))
    return builder.as_markup()


def _kb_logs(files: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for entry in files:
        name = entry["name"]
        size = entry["size_kb"]
        builder.row(
            InlineKeyboardButton(text=f"⬇️ {name} ({size}KB)", callback_data=f"maint_log_dl_{name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"maint_log_clr_{name}"),
        )
    builder.row(InlineKeyboardButton(text="🧹 Clear all logs", callback_data="maint_log_clr_all"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu_maintenance"))
    return builder.as_markup()


def _kb_ipban(banned: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for entry in banned[:15]:
        ip = entry["ip"]
        reason = entry.get("reason", "?")[:20]
        icon = "🤖" if entry.get("auto") else "✏️"
        builder.row(
            InlineKeyboardButton(text=f"{icon} {ip} ({reason})", callback_data=f"maint_unban_{ip}")
        )
    builder.row(InlineKeyboardButton(text="➕ Ban IP manually", callback_data="maint_ban_manual"))
    builder.row(InlineKeyboardButton(text="🔍 Analyze logs", callback_data="maint_analyze"))
    builder.row(InlineKeyboardButton(text="🧹 Clear auto-bans", callback_data="maint_clear_auto"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu_maintenance"))
    return builder.as_markup()


def _kb_restore_confirm() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Start restore", callback_data="maint_restore_confirm"))
    builder.row(InlineKeyboardButton(text="⬅️ Cancel", callback_data="menu_maintenance"))
    return builder.as_markup()


def _kb_windows(status: dict) -> InlineKeyboardMarkup:
    ready = status.get("ready", False)
    builder = InlineKeyboardBuilder()
    if ready:
        builder.row(InlineKeyboardButton(text="🔄 Re-download binaries", callback_data="maint_win_prefetch"))
    else:
        builder.row(InlineKeyboardButton(text="⬇️ Download binaries", callback_data="maint_win_prefetch"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu_maintenance"))
    return builder.as_markup()


def _kb_update_menu(info: dict) -> InlineKeyboardMarkup:
    git = info.get("git", {})
    job = info.get("job", {})
    running = bool(job.get("running"))
    action = str(job.get("action") or "update").lower()
    updates = bool(git.get("update_available_tag"))

    builder = InlineKeyboardBuilder()
    if running:
        running_label = (
            _txt("⏳ Переустановка выполняется", "⏳ Reinstall is running")
            if action == "reinstall"
            else _txt("⏳ Обновление выполняется", "⏳ Update is running")
        )
        builder.row(InlineKeyboardButton(text=running_label, callback_data="maint_update_menu"))
    else:
        if updates:
            builder.row(InlineKeyboardButton(text=_txt("⬆️ Обновить", "⬆️ Update"), callback_data="maint_update_run_menu"))
        builder.row(
            InlineKeyboardButton(
                text=_txt("♻️ Переустановить", "♻️ Reinstall"),
                callback_data="maint_reinstall_menu",
            )
        )

    if running or job.get("container_name"):
        builder.row(InlineKeyboardButton(text=_txt("📜 Логи", "📜 Logs"), callback_data="maint_update_logs"))
    if not running and job.get("container_name"):
        builder.row(
            InlineKeyboardButton(
                text=_txt("🧹 Очистить джоб", "🧹 Cleanup job"),
                callback_data="maint_update_cleanup",
            )
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Back", callback_data="menu_maintenance"),
    )
    return builder.as_markup()


def _kb_update_run_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_txt("⬆️ Обновить + backup", "⬆️ Update + backup"),
            callback_data="maint_update_latest_backup",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_txt("⚠️ Обновить без backup", "⚠️ Update without backup"),
            callback_data="maint_update_latest_nobackup_prompt",
        )
    )
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="maint_update_menu"))
    return builder.as_markup()


def _kb_confirm_nobackup(*, confirm_cb: str, back_cb: str = "maint_update_menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_txt("✅ Подтвердить", "✅ Confirm"), callback_data=confirm_cb))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data=back_cb))
    return builder.as_markup()


def _kb_reinstall_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_txt("♻️ Переустановить + backup", "♻️ Reinstall + backup"),
            callback_data="maint_reinstall_cur_backup",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_txt("🧹 Переустановить без backup", "🧹 Reinstall without backup"),
            callback_data="maint_reinstall_cur_nobackup_prompt",
        )
    )
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="maint_update_menu"))
    return builder.as_markup()


def _render_update_text(info: dict) -> str:
    git = info.get("git", {})
    job = info.get("job", {})

    version = git.get("current_version") or "-"
    branch = git.get("current_branch", "-")
    commit = git.get("current_commit", "-")
    current_tag = git.get("current_tag") or "—"
    latest_tag = git.get("latest_tag") or "—"
    remote_commit = git.get("remote_branch_commit") or "—"

    upd_tag = "✅ yes" if git.get("update_available_tag") else "❌ no"
    action = str(job.get("action") or "update").lower()
    mode = str(job.get("mode") or "preserve").lower()
    action_label = "update" if action == "update" else "reinstall"
    if _is_ru():
        upd_tag = "✅ да" if git.get("update_available_tag") else "❌ нет"
        action_label = "обновление" if action == "update" else "переустановка"
    if action == "reinstall":
        if _is_ru():
            action_label = "чистая переустановка" if mode == "clean" else "переустановка (с сохранением)"
        else:
            action_label = "clean reinstall" if mode == "clean" else "reinstall (keep data)"

    status = job.get("status") or ("running" if job.get("running") else "idle")
    exit_code = job.get("exit_code")
    exit_line = f"exit code: {exit_code}" if exit_code is not None else "exit code: —"
    if _is_ru():
        exit_line = f"код завершения: {exit_code}" if exit_code is not None else "код завершения: —"

    text = (
        f"⬆️ <b>{_txt('Обновления', 'Updates')}</b>\n\n"
        f"• {_txt('Версия', 'Version')}: <code>{escape(str(version))}</code>\n"
        f"• {_txt('Текущая ветка', 'Current branch')}: <code>{escape(str(branch))}</code>\n"
        f"• {_txt('Текущий коммит', 'Current commit')}: <code>{escape(str(commit))}</code>\n"
        f"• {_txt('Текущий тег', 'Current tag')}: <code>{escape(str(current_tag))}</code>\n"
        f"• {_txt('Последний тег', 'Latest tag')}: <code>{escape(str(latest_tag))}</code>\n"
        f"• {_txt('origin/ветка', 'origin/branch')}: <code>{escape(str(remote_commit))}</code>\n\n"
        f"• {_txt('Новый тег доступен', 'New tag available')}: <b>{upd_tag}</b>\n\n"
        f"• {_txt('Тип задачи', 'Job action')}: <code>{escape(action_label)}</code>\n"
        f"• {_txt('Статус джоба', 'Job status')}: <code>{escape(str(status))}</code>\n"
        f"• {exit_line}\n"
    )
    git_error = (git.get("git_error") or "").strip()
    if git_error:
        text += f"\n⚠️ <b>git:</b>\n<pre>{escape(git_error[-700:])}</pre>"
    error = (job.get("error") or "").strip()
    if error:
        text += f"\n⚠️ <b>{_txt('Ошибка джоба', 'Job error')}:</b>\n<pre>{escape(error[-700:])}</pre>"
    return text


@router.callback_query(F.data == "menu_maintenance")
async def cb_maint_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        status = await maintenance_api.status()
        text = (
            "🔧 <b>Maintenance</b>\n\n"
            f"• Backup: <b>{'every ' + str(status['backup']['auto_hours']) + 'h' if status['backup']['auto_hours'] else 'off'}</b>"
            f" (next: {status['backup']['next_at'] or '—'})\n"
            f"• Log cleanup: <b>{'every ' + str(status['logs']['auto_clean_hours']) + 'h' if status['logs']['auto_clean_hours'] else 'off'}</b>"
            f" (next: {status['logs']['next_clean_at'] or '—'})\n"
            f"• Banned IPs: <b>{status['ip_ban']['count']}</b>"
        )
        kb = _kb_main(status)
    except APIError as exc:
        text = f"❌ {exc.detail}"
        kb = kb_back("main_menu")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "maint_backup_now")
async def cb_backup_now(cq: CallbackQuery):
    await cq.answer("Creating backup…")
    try:
        pkg = await maintenance_api.backup_download_package()
        payload = pkg.get("content") or b""
        from datetime import datetime

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        archive = BufferedInputFile(payload, filename=f"backup_{ts}.zip")
        await cq.message.answer_document(
            archive,
            caption="💾 <b>Backup ready</b>",
            parse_mode="HTML",
        )
        await cq.message.answer("✅ Backup sent!", reply_markup=kb_back("menu_maintenance"))
    except APIError as exc:
        await cq.message.answer(f"❌ {escape(exc.detail)}", reply_markup=kb_back("menu_maintenance"), parse_mode="HTML")
    except Exception as exc:
        await cq.message.answer(f"❌ {escape(str(exc))}", reply_markup=kb_back("menu_maintenance"), parse_mode="HTML")


@router.callback_query(F.data == "maint_restore_zip")
async def cb_restore_zip(cq: CallbackQuery, state: FSMContext):
    await state.set_state(RestoreFSM.archive)
    await state.update_data(restore_file_id=None, restore_name=None)
    await cq.message.answer(
        "♻️ <b>Restore from ZIP</b>\n\n"
        "Send the recovery ZIP archive as a file.\n"
        "After upload, I will ask for final confirmation before restore starts.\n\n"
        "⚠️ Restore recreates the stack, so the bot and Web UI may disconnect for 30-60 seconds.",
        parse_mode="HTML",
        reply_markup=kb_back("menu_maintenance"),
    )
    await cq.answer()


@router.message(RestoreFSM.archive, F.document)
async def fsm_restore_zip_uploaded(msg: Message, state: FSMContext):
    doc = msg.document
    name = doc.file_name or ""
    if not name.lower().endswith(".zip"):
        await msg.answer(
            "❌ Send a <b>.zip</b> recovery archive.",
            parse_mode="HTML",
            reply_markup=kb_back("menu_maintenance"),
        )
        return

    await state.set_state(RestoreFSM.confirm)
    await state.update_data(restore_file_id=doc.file_id, restore_name=name)
    await msg.answer(
        "⚠️ <b>Ready to restore</b>\n\n"
        f"Archive: <code>{name}</code>\n"
        "A safety backup will be created first.\n"
        "Then the current stack will be recreated from this archive.\n\n"
        "Press <b>Start restore</b> to continue.",
        parse_mode="HTML",
        reply_markup=_kb_restore_confirm(),
    )


@router.message(RestoreFSM.archive)
async def fsm_restore_zip_waiting(msg: Message):
    await msg.answer(
        "📎 Send the recovery ZIP archive as a file.",
        reply_markup=kb_back("menu_maintenance"),
    )


@router.callback_query(RestoreFSM.confirm, F.data == "maint_restore_confirm")
async def cb_restore_confirm(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("restore_file_id")
    name = data.get("restore_name") or "backup.zip"
    if not file_id:
        await state.clear()
        await cq.message.answer("❌ Restore session expired.", reply_markup=kb_back("menu_maintenance"))
        await cq.answer()
        return

    await cq.answer("Starting restore…")
    await cq.message.edit_text(
        "⏳ <b>Starting restore...</b>\n\n"
        "Downloading the archive and scheduling the restore job.\n"
        "The bot and Web UI may disconnect shortly.",
        parse_mode="HTML",
    )

    try:
        remote_file = await cq.bot.get_file(file_id)
        payload = (await cq.bot.download_file(remote_file.file_path)).read()
        result = await maintenance_api.restore(name, payload, create_safety_backup=True)
        await state.clear()

        lines = [
            "✅ <b>Restore started</b>",
            "",
            f"Archive: <code>{name}</code>",
            "Wait 30-60 seconds, then reopen the bot or Web UI.",
        ]
        if result.get("safety_backup_path"):
            lines.append(f"Safety backup: <code>{result['safety_backup_path']}</code>")
        if result.get("restore_log_path"):
            lines.append(f"Restore log: <code>{result['restore_log_path']}</code>")

        await cq.message.answer(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=kb_back("menu_maintenance"),
        )
    except APIError as exc:
        await state.clear()
        await cq.message.answer(f"❌ {exc.detail}", reply_markup=kb_back("menu_maintenance"))
    except Exception as exc:
        await state.clear()
        await cq.message.answer(f"❌ {exc}", reply_markup=kb_back("menu_maintenance"))


@router.callback_query(F.data == "maint_backup_interval")
async def cb_backup_interval_menu(cq: CallbackQuery):
    try:
        status = await maintenance_api.status()
        current = status.get("backup", {}).get("auto_hours", 0)
    except APIError:
        current = 0
    await cq.message.edit_text(
        "⏱ <b>Auto-backup interval</b>\n\nBackup will be sent to all Telegram admins automatically.",
        reply_markup=_kb_intervals(_BACKUP_INTERVALS, "maint_bset", current),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("maint_bset_"))
async def cb_backup_set(cq: CallbackQuery):
    hours = int(cq.data.split("_")[-1])
    try:
        await maintenance_api.set_backup_interval(hours)
        label = f"every {hours}h" if hours else "off"
        await cq.answer(f"✅ Auto-backup: {label}")
        status = await maintenance_api.status()
        await cq.message.edit_text("🔧 <b>Maintenance</b>", reply_markup=_kb_main(status), parse_mode="HTML")
    except APIError as exc:
        await cq.answer(f"❌ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_logs_menu")
async def cb_logs_menu(cq: CallbackQuery):
    try:
        data = await maintenance_api.logs_list()
        files = data.get("files", [])
        text = "📋 <b>Nginx logs</b>\n\nClick ⬇️ to download, 🗑 to clear."
        kb = _kb_logs(files)
    except APIError as exc:
        text = f"❌ {exc.detail}"
        kb = kb_back("menu_maintenance")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("maint_log_dl_"))
async def cb_log_download(cq: CallbackQuery):
    name = cq.data[len("maint_log_dl_"):]
    await cq.answer("Downloading…")
    try:
        content = await maintenance_api.log_download(name)
        if content:
            file = BufferedInputFile(content if isinstance(content, bytes) else content.encode(), filename=name)
            await cq.message.answer_document(file, caption=f"📋 <code>{name}</code>", parse_mode="HTML")
        else:
            await cq.message.answer("⚠️ Log file is empty")
    except APIError as exc:
        await cq.message.answer(f"❌ {exc.detail}")


@router.callback_query(F.data.startswith("maint_log_clr_"))
async def cb_log_clear(cq: CallbackQuery):
    name = cq.data[len("maint_log_clr_"):]
    try:
        if name == "all":
            result = await maintenance_api.log_clear_all()
            cleared = result.get("cleared", [])
            await cq.answer(f"✅ Cleared {len(cleared)} files")
        else:
            await maintenance_api.log_clear_one(name)
            await cq.answer(f"✅ {name} cleared")
        data = await maintenance_api.logs_list()
        await cq.message.edit_text(
            "📋 <b>Nginx logs</b>",
            reply_markup=_kb_logs(data.get("files", [])),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"❌ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_clean_interval")
async def cb_clean_interval_menu(cq: CallbackQuery):
    try:
        status = await maintenance_api.status()
        current = status.get("logs", {}).get("auto_clean_hours", 0)
    except APIError:
        current = 0
    await cq.message.edit_text(
        "⏱ <b>Auto log cleanup interval</b>\n\nNginx access/error logs will be truncated automatically.",
        reply_markup=_kb_intervals(_CLEAN_INTERVALS, "maint_cset", current),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("maint_cset_"))
async def cb_clean_set(cq: CallbackQuery):
    hours = int(cq.data.split("_")[-1])
    try:
        await maintenance_api.set_log_clean_interval(hours)
        label = f"every {hours}h" if hours else "off"
        await cq.answer(f"✅ Auto cleanup: {label}")
        status = await maintenance_api.status()
        await cq.message.edit_text("🔧 <b>Maintenance</b>", reply_markup=_kb_main(status), parse_mode="HTML")
    except APIError as exc:
        await cq.answer(f"❌ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_ipban_menu")
async def cb_ipban_menu(cq: CallbackQuery):
    try:
        data = await maintenance_api.ip_ban_list()
        banned = data.get("banned", [])
        text = f"🚫 <b>IP Ban list</b> ({len(banned)} IPs)\n\nClick IP to unban."
        kb = _kb_ipban(banned)
    except APIError as exc:
        text = f"❌ {exc.detail}"
        kb = kb_back("menu_maintenance")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "maint_ban_manual")
async def cb_ban_manual(cq: CallbackQuery, state: FSMContext):
    await state.set_state(IpBanFSM.manual_ip)
    await cq.message.answer(
        "✏️ Enter IP address to ban (e.g. <code>1.2.3.4</code>):",
        parse_mode="HTML",
        reply_markup=kb_back("maint_ipban_menu"),
    )
    await cq.answer()


@router.message(IpBanFSM.manual_ip)
async def fsm_ban_ip(msg: Message, state: FSMContext):
    await state.clear()
    ip = (msg.text or "").strip()
    try:
        result = await maintenance_api.ip_ban_add(ip, reason="manual")
        await msg.answer(
            f"✅ <code>{ip}</code> banned\nNginx reloaded: {'✅' if result.get('nginx_reloaded') else '⚠️'}",
            parse_mode="HTML",
            reply_markup=kb_back("maint_ipban_menu"),
        )
    except APIError as exc:
        await msg.answer(f"❌ {exc.detail}", reply_markup=kb_back("maint_ipban_menu"))


@router.callback_query(F.data.startswith("maint_unban_"))
async def cb_unban(cq: CallbackQuery):
    ip = cq.data[len("maint_unban_"):]
    try:
        await maintenance_api.ip_ban_remove(ip)
        await cq.answer(f"✅ {ip} unbanned")
        data = await maintenance_api.ip_ban_list()
        banned = data.get("banned", [])
        await cq.message.edit_text(
            f"🚫 <b>IP Ban list</b> ({len(banned)} IPs)",
            reply_markup=_kb_ipban(banned),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"❌ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_analyze")
async def cb_analyze(cq: CallbackQuery):
    await cq.answer("Analyzing logs…")
    try:
        data = await maintenance_api.ip_ban_analyze()
        suspicious = data.get("suspicious", [])
        if not suspicious:
            await cq.message.answer("✅ No suspicious IPs found in logs.", reply_markup=kb_back("maint_ipban_menu"))
            return

        lines = [f"• <code>{entry['ip']}</code> — {entry['reason']}" for entry in suspicious[:20]]
        text = f"🔍 <b>Suspicious IPs ({len(suspicious)}):</b>\n" + "\n".join(lines)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"🚫 Ban all {len(suspicious)} IPs", callback_data="maint_ban_all_analyzed")],
                [InlineKeyboardButton(text="⬅️ Back", callback_data="maint_ipban_menu")],
            ]
        )
        await cq.message.answer(text, reply_markup=kb, parse_mode="HTML")
    except APIError as exc:
        await cq.message.answer(f"❌ {exc.detail}", reply_markup=kb_back("maint_ipban_menu"))


@router.callback_query(F.data == "maint_ban_all_analyzed")
async def cb_ban_all_analyzed(cq: CallbackQuery):
    await cq.answer("Banning…")
    try:
        result = await maintenance_api.ip_ban_all_analyzed()
        count = result.get("banned", 0)
        await cq.message.edit_text(
            f"✅ Banned <b>{count}</b> IPs. Nginx reloaded.",
            reply_markup=kb_back("maint_ipban_menu"),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"❌ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_clear_auto")
async def cb_clear_auto_bans(cq: CallbackQuery):
    try:
        result = await maintenance_api.ip_ban_clear_auto()
        count = result.get("removed", 0)
        await cq.answer(f"✅ Removed {count} auto-bans")
        data = await maintenance_api.ip_ban_list()
        await cq.message.edit_text(
            f"🚫 <b>IP Ban list</b> ({len(data.get('banned', []))} IPs)",
            reply_markup=_kb_ipban(data.get("banned", [])),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"❌ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_windows")
async def cb_windows_menu(cq: CallbackQuery):
    try:
        status = await maintenance_api.windows_binaries_status()
        version = status.get("sing_box_version", "?")
        sing_box = "✅" if status.get("sing_box_cached") else "❌"
        winsw = "✅" if status.get("winsw_cached") else "❌"
        ready = status.get("ready", False)
        state_text = "✅ Ready — clients can download ZIP" if ready else "⚠️ Binaries not downloaded yet"
        await cq.message.edit_text(
            f"🪟 <b>Windows Service Binaries</b>\n\n"
            f"{sing_box} sing-box.exe (v{version})\n"
            f"{winsw} winsw3.exe\n\n"
            f"{state_text}\n\n"
            "After downloading, each client can get a ready-to-use ZIP archive "
            "(sing-box.exe + winsw3.exe + scripts + XML) via Sub URL.",
            reply_markup=_kb_windows(status),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"❌ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_win_prefetch")
async def cb_win_prefetch(cq: CallbackQuery):
    await cq.answer("⏳ Downloading… this may take 1-2 minutes")
    await cq.message.edit_text(
        "⏳ <b>Downloading Windows binaries...</b>\n\n"
        "• sing-box.exe (Windows AMD64)\n"
        "• winsw3.exe\n\n"
        "Please wait, this usually takes 1-2 minutes.",
        parse_mode="HTML",
    )
    try:
        await maintenance_api.prefetch_windows_binaries()
        status = await maintenance_api.windows_binaries_status()
        await cq.message.edit_text(
            "✅ <b>Windows binaries downloaded!</b>\n\n"
            "Clients can now download the Windows Service ZIP from their Sub URL.",
            reply_markup=_kb_windows(status),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.edit_text(
            f"❌ <b>Download failed</b>\n\n{exc.detail}\n\n"
            "Check that the server has internet access and try again.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🔄 Retry", callback_data="maint_win_prefetch"),
                        InlineKeyboardButton(text="⬅️ Back", callback_data="maint_windows"),
                    ]
                ]
            ),
            parse_mode="HTML",
        )


# в”Ђв”Ђв”Ђ Updates в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

@router.callback_query(F.data == "maint_update_menu")
async def cb_update_menu(cq: CallbackQuery):
    await cq.answer()
    try:
        info = await maintenance_api.update_info()
        await cq.message.edit_text(
            _render_update_text(info),
            reply_markup=_kb_update_menu(info),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.edit_text(
            f"❌ {escape(exc.detail)}",
            reply_markup=kb_back("menu_maintenance"),
            parse_mode="HTML",
        )


async def _run_update(cq: CallbackQuery, *, with_backup: bool) -> None:
    await cq.answer(_txt("Запускаю обновление…", "Starting update…"))
    try:
        info = await maintenance_api.update_info()
        if info.get("job", {}).get("running"):
            await cq.message.answer(
                _txt("⏳ Уже выполняется другая задача обслуживания.", "⏳ A maintenance job is already running."),
                reply_markup=kb_back("maint_update_menu"),
            )
            return
        git = info.get("git", {})
        has_updates = bool(git.get("update_available_tag"))
        if not has_updates:
            await cq.message.answer(
                _txt("ℹ️ Новых обновлений не обнаружено.", "ℹ️ No updates detected."),
                reply_markup=kb_back("maint_update_menu"),
            )
            return

        backup_path = ""
        if with_backup:
            detected_path = await _send_preflight_backup(cq, reason_ru="update", reason_en="update")
            if not detected_path:
                return
            backup_path = detected_path

        result = await maintenance_api.update_run(
            target="latest_tag",
            with_backup=with_backup,
            backup_path=backup_path or None,
        )
        target_ref = result.get("target_ref") or git.get("latest_tag") or "-"
        ru_msg = (
            f"✅ Обновление запущено.\nТег: <code>{escape(str(target_ref))}</code>\n"
            "Backup+restore включены.\n"
            "Проверьте логи через 10-20 секунд."
            if with_backup
            else
            f"✅ Обновление запущено.\nТег: <code>{escape(str(target_ref))}</code>\n"
            "Запущено без backup/restore.\n"
            "Проверьте логи через 10-20 секунд."
        )
        en_msg = (
            f"✅ Update started.\nTag: <code>{escape(str(target_ref))}</code>\n"
            "Backup+restore enabled.\n"
            "Check logs in 10-20 seconds."
            if with_backup
            else
            f"✅ Update started.\nTag: <code>{escape(str(target_ref))}</code>\n"
            "Started without backup/restore.\n"
            "Check logs in 10-20 seconds."
        )
        await cq.message.answer(
            _txt(ru_msg, en_msg),
            parse_mode="HTML",
            reply_markup=kb_back("maint_update_menu"),
        )
        # Refresh current page as well
        fresh = await maintenance_api.update_info()
        await cq.message.edit_text(
            _render_update_text(fresh),
            reply_markup=_kb_update_menu(fresh),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.answer(f"❌ {escape(exc.detail)}", reply_markup=kb_back("maint_update_menu"), parse_mode="HTML")


@router.callback_query(F.data == "maint_update_run")
async def cb_update_run_legacy(cq: CallbackQuery):
    # Backward-compatible callback: update with backup
    await _run_update(cq, with_backup=True)


@router.callback_query(F.data == "maint_update_run_menu")
async def cb_update_run_menu(cq: CallbackQuery):
    await cq.answer()
    latest_tag = "-"
    notes = ""
    try:
        info = await maintenance_api.update_info()
        git = info.get("git", {})
        latest_tag = (git.get("latest_tag") or "-").strip() or "-"
        notes = _pick_localized_notes(git, "ru" if _is_ru() else "en")
    except APIError:
        pass

    if notes:
        notes_block = _txt(
            f"\n\n<b>Что нового в {escape(latest_tag)}:</b>\n<pre>{escape(notes[-1800:])}</pre>",
            f"\n\n<b>What's new in {escape(latest_tag)}:</b>\n<pre>{escape(notes[-1800:])}</pre>",
        )
    else:
        notes_block = _txt(
            f"\n\n<b>Что нового в {escape(latest_tag)}:</b>\n<i>Описание релиза не указано.</i>",
            f"\n\n<b>What's new in {escape(latest_tag)}:</b>\n<i>No release notes provided.</i>",
        )

    text = _txt(
        "⬆️ <b>Обновление</b>\n\n"
        "Доступны два режима:\n"
        "• С backup: отправляем архив, затем update и restore.\n"
        "• Без backup: update без restore (требует подтверждение).",
        "⬆️ <b>Update</b>\n\n"
        "Two modes are available:\n"
        "• With backup: send archive, then update and restore.\n"
        "• Without backup: update without restore (requires confirmation).",
    )
    await cq.message.edit_text(
        text + notes_block,
        reply_markup=_kb_update_run_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "maint_update_latest_backup")
async def cb_update_latest_backup(cq: CallbackQuery):
    await _run_update(cq, with_backup=True)


@router.callback_query(F.data == "maint_update_latest_nobackup_prompt")
async def cb_update_latest_nobackup_prompt(cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        _txt(
            "⚠️ <b>Обновление без backup</b>\n\n"
            "В этом режиме не будет создан архив и не будет restore.\n"
            "Продолжить?",
            "⚠️ <b>Update without backup</b>\n\n"
            "No archive will be created and no restore will be performed.\n"
            "Continue?",
        ),
        reply_markup=_kb_confirm_nobackup(
            confirm_cb="maint_update_latest_nobackup_confirm",
            back_cb="maint_update_run_menu",
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "maint_update_latest_nobackup_confirm")
async def cb_update_latest_nobackup_confirm(cq: CallbackQuery):
    await _run_update(cq, with_backup=False)


@router.callback_query(F.data == "maint_reinstall_menu")
async def cb_reinstall_menu(cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        _txt(
            "♻️ <b>Переустановка</b>\n\n"
            "Переустановка всегда выполняется на текущую установленную версию.\n"
            "Выберите режим:\n"
            "• C backup: сначала отправить backup, затем hard reinstall и restore.\n"
            "• Без backup: только hard reinstall без restore.",
            "♻️ <b>Reinstall</b>\n\n"
            "Reinstall always runs for the currently installed version.\n"
            "Choose mode:\n"
            "• With backup: send backup first, then hard reinstall and restore.\n"
            "• Without backup: hard reinstall only, no restore.",
        ),
        reply_markup=_kb_reinstall_menu(),
        parse_mode="HTML",
    )


async def _run_reinstall(cq: CallbackQuery, *, with_backup: bool) -> None:
    await cq.answer(
        _txt("Запускаю переустановку…", "Starting reinstall…")
    )
    try:
        info = await maintenance_api.update_info()
        if info.get("job", {}).get("running"):
            await cq.message.answer(
                _txt("⏳ Уже выполняется другая задача обслуживания.", "⏳ A maintenance job is already running."),
                reply_markup=kb_back("maint_update_menu"),
            )
            return

        backup_path = ""
        if with_backup:
            detected_path = await _send_preflight_backup(cq, reason_ru="reinstall", reason_en="reinstall")
            if not detected_path:
                return
            backup_path = detected_path

        await maintenance_api.reinstall_run(
            clean=True,
            target="current",
            with_backup=with_backup,
            backup_path=backup_path or None,
        )
        ru_msg = (
            "✅ Переустановка запущена (current version).\n"
            "Бот/веб могут быть недоступны 30-60 секунд.\n"
            "Backup+restore включены."
            if with_backup
            else
            "✅ Переустановка запущена (current version).\n"
            "Бот/веб могут быть недоступны 30-60 секунд.\n"
            "Запущено без backup/restore."
        )
        en_msg = (
            "✅ Reinstall started (current version).\n"
            "Bot/Web may be unavailable for 30-60 seconds.\n"
            "Backup+restore enabled."
            if with_backup
            else
            "✅ Reinstall started (current version).\n"
            "Bot/Web may be unavailable for 30-60 seconds.\n"
            "Started without backup/restore."
        )
        await cq.message.answer(_txt(ru_msg, en_msg), reply_markup=kb_back("maint_update_menu"))
        fresh = await maintenance_api.update_info()
        await cq.message.edit_text(
            _render_update_text(fresh),
            reply_markup=_kb_update_menu(fresh),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.answer(f"❌ {escape(exc.detail)}", reply_markup=kb_back("maint_update_menu"), parse_mode="HTML")


@router.callback_query(F.data == "maint_reinstall_cur_backup")
async def cb_reinstall_cur_backup(cq: CallbackQuery):
    await _run_reinstall(cq, with_backup=True)


@router.callback_query(F.data == "maint_reinstall_cur_nobackup_prompt")
async def cb_reinstall_cur_nobackup_prompt(cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        _txt(
            "⚠️ <b>Переустановка без backup</b>\n\n"
            "В этом режиме не будет создан архив и не будет restore.\n"
            "Продолжить?",
            "⚠️ <b>Reinstall without backup</b>\n\n"
            "No archive will be created and no restore will be performed.\n"
            "Continue?",
        ),
        reply_markup=_kb_confirm_nobackup(
            confirm_cb="maint_reinstall_cur_nobackup_confirm",
            back_cb="maint_reinstall_menu",
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "maint_reinstall_cur_nobackup_confirm")
async def cb_reinstall_cur_nobackup_confirm(cq: CallbackQuery):
    await _run_reinstall(cq, with_backup=False)


@router.callback_query(F.data == "maint_update_logs")
async def cb_update_logs(cq: CallbackQuery):
    await cq.answer()
    try:
        data = await maintenance_api.update_logs(lines=220)
        logs = (data.get("logs") or "").strip()
        if not logs:
            logs = _txt("Логи пока пустые.", "No logs yet.")
        status = data.get("status", "unknown")
        running = data.get("running", False)
        action = str(data.get("action") or "update").lower()
        if action == "reinstall":
            title = _txt("📜 Логи переустановки", "📜 Reinstall logs")
        else:
            title = _txt("📜 Логи обновления", "📜 Update logs")
        state_line = (
            _txt("⏳ Выполняется", "⏳ Running")
            if running
            else _txt(f"✅ Завершено ({status})", f"✅ Finished ({status})")
        )
        text = f"{title}\n{state_line}\n\n<pre>{escape(logs[-3500:])}</pre>"
        await cq.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=_txt("🔄 Обновить логи", "🔄 Refresh logs"), callback_data="maint_update_logs")],
                    [InlineKeyboardButton(text="⬅️ Back", callback_data="maint_update_menu")],
                ]
            ),
        )
    except APIError as exc:
        await cq.message.answer(f"❌ {escape(exc.detail)}", reply_markup=kb_back("maint_update_menu"), parse_mode="HTML")


@router.callback_query(F.data == "maint_update_cleanup")
async def cb_update_cleanup(cq: CallbackQuery):
    await cq.answer(_txt("Очищаю…", "Cleaning…"))
    try:
        await maintenance_api.update_cleanup()
        info = await maintenance_api.update_info()
        await cq.message.edit_text(
            _render_update_text(info),
            reply_markup=_kb_update_menu(info),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.answer(f"❌ {escape(exc.detail)}", reply_markup=kb_back("maint_update_menu"), parse_mode="HTML")



