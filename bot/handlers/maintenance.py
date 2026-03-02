"""
Maintenance section: backup, IP ban, log management.
"""
import io
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.api_client import maintenance_api, APIError
from bot.keyboards.main import kb_back

router = Router()

# ─── Interval options ─────────────────────────────────────────────────────────

_BACKUP_INTERVALS = [
    ("🚫 Off",       0),
    ("6 hours",      6),
    ("12 hours",     12),
    ("24 hours",     24),
    ("48 hours",     48),
    ("7 days",       168),
]

_CLEAN_INTERVALS = [
    ("🚫 Off",       0),
    ("24 hours",     24),
    ("3 days",       72),
    ("7 days",       168),
    ("30 days",      720),
]


class IpBanFSM(StatesGroup):
    manual_ip = State()


# ─── Keyboards ────────────────────────────────────────────────────────────────

def _kb_main(status: dict) -> InlineKeyboardMarkup:
    b_hours = status.get("backup", {}).get("auto_hours", 0)
    c_hours = status.get("logs", {}).get("auto_clean_hours", 0)
    ban_cnt = status.get("ip_ban", {}).get("count", 0)
    b_next  = status.get("backup", {}).get("next_at") or "—"
    c_next  = status.get("logs", {}).get("next_clean_at") or "—"

    b_label = f"{'🔄' if b_hours else '⏸'} Backup: {'every ' + str(b_hours) + 'h' if b_hours else 'off'}"
    c_label = f"{'🧹' if c_hours else '⏸'} Log clean: {'every ' + str(c_hours) + 'h' if c_hours else 'off'}"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💾 Backup now",    callback_data="maint_backup_now"))
    builder.row(InlineKeyboardButton(text=b_label,            callback_data="maint_backup_interval"))
    builder.row(InlineKeyboardButton(text="📋 Logs",          callback_data="maint_logs_menu"))
    builder.row(InlineKeyboardButton(text=c_label,            callback_data="maint_clean_interval"))
    builder.row(InlineKeyboardButton(text=f"🚫 IP Ban ({ban_cnt})", callback_data="maint_ipban_menu"))
    builder.row(InlineKeyboardButton(text="🪟 Windows Service",   callback_data="maint_windows"))
    builder.row(InlineKeyboardButton(text="⬅️ Back",               callback_data="main_menu"))
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
    for f in files:
        name = f["name"]
        size = f["size_kb"]
        builder.row(
            InlineKeyboardButton(text=f"⬇️ {name} ({size}KB)", callback_data=f"maint_log_dl_{name}"),
            InlineKeyboardButton(text="🗑",                     callback_data=f"maint_log_clr_{name}"),
        )
    builder.row(InlineKeyboardButton(text="🧹 Clear all logs",  callback_data="maint_log_clr_all"))
    builder.row(InlineKeyboardButton(text="⬅️ Back",             callback_data="menu_maintenance"))
    return builder.as_markup()


def _kb_ipban(banned: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for entry in banned[:15]:
        ip = entry["ip"]
        reason = entry.get("reason", "?")[:20]
        auto = "🤖" if entry.get("auto") else "✏️"
        builder.row(
            InlineKeyboardButton(text=f"{auto} {ip} ({reason})", callback_data=f"maint_unban_{ip}"),
        )
    builder.row(InlineKeyboardButton(text="➕ Ban IP manually",   callback_data="maint_ban_manual"))
    builder.row(InlineKeyboardButton(text="🔍 Analyze logs",      callback_data="maint_analyze"))
    builder.row(InlineKeyboardButton(text="🧹 Clear auto-bans",   callback_data="maint_clear_auto"))
    builder.row(InlineKeyboardButton(text="⬅️ Back",               callback_data="menu_maintenance"))
    return builder.as_markup()


# ─── Entry / main ─────────────────────────────────────────────────────────────

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
    except APIError as e:
        text = f"❌ {e.detail}"
        kb = kb_back("main_menu")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ─── Backup ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "maint_backup_now")
async def cb_backup_now(cq: CallbackQuery):
    await cq.answer("Creating backup…")
    try:
        import httpx
        from api.config import settings
        async with httpx.AsyncClient(
            base_url="http://localhost:8080",
            headers={"X-Internal-Token": settings.internal_token},
            timeout=60,
        ) as client:
            r = await client.get("/api/maintenance/backup/download")
            if r.is_success:
                from datetime import datetime
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
                file = BufferedInputFile(r.content, filename=f"backup_{ts}.zip")
                await cq.message.answer_document(file, caption="💾 <b>Backup ready</b>", parse_mode="HTML")
                await cq.message.answer("✅ Backup sent!", reply_markup=kb_back("menu_maintenance"))
            else:
                await cq.message.answer("❌ Backup failed", reply_markup=kb_back("menu_maintenance"))
    except Exception as e:
        await cq.message.answer(f"❌ {e}", reply_markup=kb_back("menu_maintenance"))


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
        await cq.message.edit_text(
            "🔧 <b>Maintenance</b>",
            reply_markup=_kb_main(status),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── Logs ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "maint_logs_menu")
async def cb_logs_menu(cq: CallbackQuery):
    try:
        data = await maintenance_api.logs_list()
        files = data.get("files", [])
        text = "📋 <b>Nginx logs</b>\n\nClick ⬇️ to download, 🗑 to clear."
        kb = _kb_logs(files)
    except APIError as e:
        text = f"❌ {e.detail}"
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
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}")


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
        # Refresh log menu
        data = await maintenance_api.logs_list()
        await cq.message.edit_text(
            "📋 <b>Nginx logs</b>",
            reply_markup=_kb_logs(data.get("files", [])),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


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
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── IP Ban ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "maint_ipban_menu")
async def cb_ipban_menu(cq: CallbackQuery):
    try:
        data = await maintenance_api.ip_ban_list()
        banned = data.get("banned", [])
        text = f"🚫 <b>IP Ban list</b> ({len(banned)} IPs)\n\nClick IP to unban."
        kb = _kb_ipban(banned)
    except APIError as e:
        text = f"❌ {e.detail}"
        kb = kb_back("menu_maintenance")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "maint_ban_manual")
async def cb_ban_manual(cq: CallbackQuery, state: FSMContext):
    await state.set_state(IpBanFSM.manual_ip)
    await cq.message.answer("✏️ Enter IP address to ban (e.g. <code>1.2.3.4</code>):",
                            parse_mode="HTML", reply_markup=kb_back("maint_ipban_menu"))
    await cq.answer()


@router.message(IpBanFSM.manual_ip)
async def fsm_ban_ip(msg: Message, state: FSMContext):
    await state.clear()
    ip = msg.text.strip()
    try:
        result = await maintenance_api.ip_ban_add(ip, reason="manual")
        await msg.answer(
            f"✅ <code>{ip}</code> banned\nNginx reloaded: {'✅' if result.get('nginx_reloaded') else '⚠️'}",
            parse_mode="HTML", reply_markup=kb_back("maint_ipban_menu"),
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("maint_ipban_menu"))


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
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data == "maint_analyze")
async def cb_analyze(cq: CallbackQuery):
    await cq.answer("Analyzing logs…")
    try:
        data = await maintenance_api.ip_ban_analyze()
        suspicious = data.get("suspicious", [])
        if not suspicious:
            await cq.message.answer("✅ No suspicious IPs found in logs.", reply_markup=kb_back("maint_ipban_menu"))
            return

        lines = []
        for s in suspicious[:20]:
            lines.append(f"• <code>{s['ip']}</code> — {s['reason']}")
        text = f"🔍 <b>Suspicious IPs ({len(suspicious)}):</b>\n" + "\n".join(lines)

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🚫 Ban all {len(suspicious)} IPs", callback_data="maint_ban_all_analyzed")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="maint_ipban_menu")],
        ])
        await cq.message.answer(text, reply_markup=kb, parse_mode="HTML")
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}", reply_markup=kb_back("maint_ipban_menu"))


@router.callback_query(F.data == "maint_ban_all_analyzed")
async def cb_ban_all_analyzed(cq: CallbackQuery):
    await cq.answer("Banning…")
    try:
        result = await maintenance_api.ip_ban_all_analyzed()
        n = result.get("banned", 0)
        await cq.message.edit_text(
            f"✅ Banned <b>{n}</b> IPs. Nginx reloaded.",
            reply_markup=kb_back("maint_ipban_menu"),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data == "maint_clear_auto")
async def cb_clear_auto_bans(cq: CallbackQuery):
    try:
        result = await maintenance_api.ip_ban_clear_auto()
        n = result.get("removed", 0)
        await cq.answer(f"✅ Removed {n} auto-bans")
        data = await maintenance_api.ip_ban_list()
        await cq.message.edit_text(
            f"🚫 <b>IP Ban list</b> ({len(data.get('banned', []))} IPs)",
            reply_markup=_kb_ipban(data.get("banned", [])),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── Windows Service ───────────────────────────────────────────────────────────

def _kb_windows(status: dict) -> InlineKeyboardMarkup:
    ready = status.get("ready", False)
    builder = InlineKeyboardBuilder()
    if not ready:
        builder.row(InlineKeyboardButton(text="⬇️ Download binaries", callback_data="maint_win_prefetch"))
    else:
        builder.row(InlineKeyboardButton(text="🔄 Re-download binaries", callback_data="maint_win_prefetch"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu_maintenance"))
    return builder.as_markup()


@router.callback_query(F.data == "maint_windows")
async def cb_windows_menu(cq: CallbackQuery):
    try:
        status = await maintenance_api.windows_binaries_status()
        ver = status.get("sing_box_version", "?")
        sb  = "✅" if status.get("sing_box_cached") else "❌"
        ws  = "✅" if status.get("winsw_cached") else "❌"
        ready = status.get("ready", False)
        state_txt = "✅ Ready — clients can download ZIP" if ready else "⚠️ Binaries not downloaded yet"
        await cq.message.edit_text(
            f"🪟 <b>Windows Service Binaries</b>\n\n"
            f"{sb} sing-box.exe (v{ver})\n"
            f"{ws} winsw3.exe\n\n"
            f"{state_txt}\n\n"
            f"After downloading, each client can get a ready-to-use ZIP archive "
            f"(sing-box.exe + winsw3.exe + scripts + XML) via Sub URL.",
            reply_markup=_kb_windows(status),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


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
    except APIError as e:
        await cq.message.edit_text(
            f"❌ <b>Download failed</b>\n\n{e.detail}\n\n"
            "Check that the server has internet access and try again.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔄 Retry", callback_data="maint_win_prefetch"),
                InlineKeyboardButton(text="⬅️ Back", callback_data="maint_windows"),
            ]]),
            parse_mode="HTML",
        )
