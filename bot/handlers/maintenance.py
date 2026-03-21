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

_BACKUP_INTERVALS = [0, 6, 12, 24, 48, 168]
_CLEAN_INTERVALS = [0, 24, 72, 168, 720]


class IpBanFSM(StatesGroup):
    manual_ip = State()


class RestoreFSM(StatesGroup):
    archive = State()
    confirm = State()


class WarpFSM(StatesGroup):
    license_key = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


def _ru_plural(num: int, one: str, few: str, many: str) -> str:
    n = abs(num)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return few
    return many


def _duration_label(hours: int) -> str:
    if hours == 0:
        return _txt("рџљ« Р’С‹РєР»", "рџљ« Off")
    if hours % 24 == 0:
        days = hours // 24
        day_ru = _ru_plural(days, "РґРµРЅСЊ", "РґРЅСЏ", "РґРЅРµР№")
        day_en = "day" if days == 1 else "days"
        return _txt(f"{days} {day_ru}", f"{days} {day_en}")
    hour_ru = _ru_plural(hours, "С‡Р°СЃ", "С‡Р°СЃР°", "С‡Р°СЃРѕРІ")
    hour_en = "hour" if hours == 1 else "hours"
    return _txt(f"{hours} {hour_ru}", f"{hours} {hour_en}")


def _schedule_label(hours: int) -> str:
    if hours <= 0:
        return _txt("РІС‹РєР»", "off")
    return _txt(f"РєР°Р¶РґС‹Рµ {hours}С‡", f"every {hours}h")


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
        caption = _txt(f"Backup РїРµСЂРµРґ {reason_ru}", f"Backup before {reason_en}")
        await cq.message.answer_document(archive, caption=caption, parse_mode="HTML")
        if not backup_path:
            await cq.message.answer(
                _txt("РќРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ РїСѓС‚СЊ backup РЅР° СЃРµСЂРІРµСЂРµ.", "Cannot detect backup path on server."),
                reply_markup=kb_back("maint_update_menu"),
            )
            return None
        return backup_path
    except APIError as exc:
        await cq.message.answer(
            _txt(
                f"РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґРіРѕС‚РѕРІРёС‚СЊ backup: <code>{escape(exc.detail)}</code>",
                f"Failed to prepare backup: <code>{escape(exc.detail)}</code>",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("maint_update_menu"),
        )
        return None
    except Exception as exc:
        await cq.message.answer(
            _txt(
                f"РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґРіРѕС‚РѕРІРёС‚СЊ backup: <code>{escape(str(exc))}</code>",
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
    b_label = _txt(
        f"рџ’ѕ Backup ({_schedule_label(b_hours)})",
        f"рџ’ѕ Backup ({_schedule_label(b_hours)})",
    )
    l_label = _txt(
        f"рџ“‹ Р›РѕРіРё ({_schedule_label(c_hours)}, IP Ban: {ban_cnt})",
        f"рџ“‹ Logs ({_schedule_label(c_hours)}, IP Ban: {ban_cnt})",
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=b_label, callback_data="maint_backup_menu"))
    builder.row(InlineKeyboardButton(text=l_label, callback_data="maint_logs_root"))
    builder.row(InlineKeyboardButton(text=_txt("рџ”ђ SSH РїРѕСЂС‚", "рџ”ђ SSH port"), callback_data="server_ssh_port"))
    builder.row(InlineKeyboardButton(text=_txt("рџЄџ Windows Service", "рџЄџ Windows Service"), callback_data="maint_windows"))
    builder.row(InlineKeyboardButton(text=_txt("в¬†пёЏ РћР±РЅРѕРІР»РµРЅРёСЏ", "в¬†пёЏ Updates"), callback_data="maint_update_menu"))
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="main_menu"))
    return builder.as_markup()


def _kb_backup_menu(status: dict) -> InlineKeyboardMarkup:
    b_hours = int(status.get("backup", {}).get("auto_hours", 0) or 0)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_txt("рџ’ѕ Backup СЃРµР№С‡Р°СЃ", "рџ’ѕ Backup now"), callback_data="maint_backup_now"))
    builder.row(InlineKeyboardButton(text=_txt("в™»пёЏ Restore ZIP", "в™»пёЏ Restore ZIP"), callback_data="maint_restore_zip"))
    builder.row(
        InlineKeyboardButton(
            text=_txt(f"вЏ± РђРІС‚Рѕ-backup: {_schedule_label(b_hours)}", f"вЏ± Auto-backup: {_schedule_label(b_hours)}"),
            callback_data="maint_backup_interval",
        )
    )
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="menu_maintenance"))
    return builder.as_markup()


def _kb_logs_root(status: dict) -> InlineKeyboardMarkup:
    c_hours = int(status.get("logs", {}).get("auto_clean_hours", 0) or 0)
    ban_cnt = int(status.get("ip_ban", {}).get("count", 0) or 0)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_txt("рџ“‹ Р›РѕРіРё Nginx", "рџ“‹ Nginx logs"), callback_data="maint_logs_menu"))
    builder.row(
        InlineKeyboardButton(
            text=_txt(f"вЏ± РђРІС‚Рѕ-РѕС‡РёСЃС‚РєР°: {_schedule_label(c_hours)}", f"вЏ± Auto cleanup: {_schedule_label(c_hours)}"),
            callback_data="maint_clean_interval",
        )
    )
    builder.row(InlineKeyboardButton(text=_txt(f"рџљ« IP Ban ({ban_cnt})", f"рџљ« IP Ban ({ban_cnt})"), callback_data="maint_ipban_menu"))
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="menu_maintenance"))
    return builder.as_markup()


def _kb_intervals(items: list, prefix: str, current: int, *, back_cb: str = "menu_maintenance") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for hours in items:
        tick = "вњ… " if hours == current else ""
        builder.row(
            InlineKeyboardButton(text=f"{tick}{_duration_label(hours)}", callback_data=f"{prefix}_{hours}")
        )
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data=back_cb))
    return builder.as_markup()


def _kb_logs(files: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for entry in files:
        name = entry["name"]
        size = entry["size_kb"]
        builder.row(
            InlineKeyboardButton(text=f"в¬‡пёЏ {name} ({size}KB)", callback_data=f"maint_log_dl_{name}"),
            InlineKeyboardButton(text="рџ—‘", callback_data=f"maint_log_clr_{name}"),
        )
    builder.row(InlineKeyboardButton(text=_txt("рџ§№ РћС‡РёСЃС‚РёС‚СЊ РІСЃРµ Р»РѕРіРё", "рџ§№ Clear all logs"), callback_data="maint_log_clr_all"))
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="maint_logs_root"))
    return builder.as_markup()


def _kb_ipban(banned: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for entry in banned[:15]:
        ip = entry["ip"]
        reason = entry.get("reason", "?")[:20]
        icon = "рџ¤–" if entry.get("auto") else "вњЏпёЏ"
        builder.row(
            InlineKeyboardButton(text=f"{icon} {ip} ({reason})", callback_data=f"maint_unban_{ip}")
        )
    builder.row(InlineKeyboardButton(text=_txt("вћ• Р—Р°Р±Р»РѕРєРёСЂРѕРІР°С‚СЊ IP РІСЂСѓС‡РЅСѓСЋ", "вћ• Ban IP manually"), callback_data="maint_ban_manual"))
    builder.row(InlineKeyboardButton(text=_txt("рџ”Ќ РђРЅР°Р»РёР· Р»РѕРіРѕРІ", "рџ”Ќ Analyze logs"), callback_data="maint_analyze"))
    builder.row(InlineKeyboardButton(text=_txt("рџ§№ РћС‡РёСЃС‚РёС‚СЊ Р°РІС‚Рѕ-Р±Р°РЅС‹", "рџ§№ Clear auto-bans"), callback_data="maint_clear_auto"))
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="maint_logs_root"))
    return builder.as_markup()


def _kb_restore_confirm() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_txt("вњ… РќР°С‡Р°С‚СЊ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёРµ", "вњ… Start restore"), callback_data="maint_restore_confirm"))
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РћС‚РјРµРЅР°", "в¬…пёЏ Cancel"), callback_data="maint_backup_menu"))
    return builder.as_markup()


def _kb_windows(status: dict) -> InlineKeyboardMarkup:
    ready = status.get("ready", False)
    builder = InlineKeyboardBuilder()
    if ready:
        builder.row(
            InlineKeyboardButton(
                text=_txt("рџ”„ РџРµСЂРµРєР°С‡Р°С‚СЊ Р±РёРЅР°СЂРЅРёРєРё", "рџ”„ Re-download binaries"),
                callback_data="maint_win_prefetch",
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=_txt("в¬‡пёЏ РЎРєР°С‡Р°С‚СЊ Р±РёРЅР°СЂРЅРёРєРё", "в¬‡пёЏ Download binaries"),
                callback_data="maint_win_prefetch",
            )
        )
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="menu_maintenance"))
    return builder.as_markup()


def _render_warp_text(data: dict) -> str:
    enabled = bool(data.get("enabled"))
    key_set = bool(data.get("license_key_set"))
    key_masked = data.get("license_key_masked") or "РІР‚вЂќ"
    runtime = data.get("runtime", {}) or {}
    available = bool(runtime.get("available"))
    running = bool(runtime.get("running"))
    service_running = bool(runtime.get("service_running"))
    warp_mode = str(runtime.get("warp") or "off")
    container = runtime.get("resolved_container") or runtime.get("container") or "РІР‚вЂќ"
    error = (runtime.get("error") or "").strip()

    text = (
        f"СЂСџРЉв‚¬ <b>WARP</b>\n\n"
        f"РІР‚Сћ {_txt('Р В Р ВµР В¶Р С‘Р С', 'Mode')}: <b>{'ON' if enabled else 'OFF'}</b>\n"
        f"РІР‚Сћ {_txt('Р С™Р В»РЎР‹РЎвЂЎ WARP+', 'WARP+ key')}: <code>{escape(str(key_masked))}</code>"
        f" ({_txt('РЎС“РЎРѓРЎвЂљР В°Р Р…Р С•Р Р†Р В»Р ВµР Р…', 'set') if key_set else _txt('Р Р…Р Вµ РЎС“РЎРѓРЎвЂљР В°Р Р…Р С•Р Р†Р В»Р ВµР Р…', 'not set')})\n"
        f"РІР‚Сћ {_txt('Р С™Р С•Р Р…РЎвЂљР ВµР в„–Р Р…Р ВµРЎР‚', 'Container')}: <code>{escape(str(container))}</code>\n"
        f"РІР‚Сћ {_txt('Р”РѕСЃС‚СѓРїРµРЅ', 'Available')}: {'РІСљвЂ¦' if available else 'РІСњРЉ'}\n"
        f"РІР‚Сћ {_txt('Р вЂ”Р В°Р С—РЎС“РЎвЂ°Р ВµР Р…', 'Running')}: {'РІСљвЂ¦' if running else 'РІСњРЉ'}\n"
        f"РІР‚Сћ {_txt('warp-svc', 'warp-svc')}: {'РІСљвЂ¦' if service_running else 'РІСњРЉ'}\n"
        f"РІР‚Сћ {_txt('Cloudflare trace', 'Cloudflare trace')}: <code>{escape(warp_mode)}</code>\n"
    )
    if error:
        text += f"\nРІС™В РїС‘РЏ <b>{_txt('Р С›РЎв‚¬Р С‘Р В±Р С”Р В°', 'Error')}</b>: <code>{escape(error)}</code>"
    return text


def _kb_warp(data: dict, *, back_cb: str = "main_menu", cb_prefix: str = "menu_warp") -> InlineKeyboardMarkup:
    enabled = bool(data.get("enabled"))
    key_set = bool(data.get("license_key_set"))
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_txt("СЂСџвЂќТ‘ Р вЂ™РЎвЂ№Р С”Р В»РЎР‹РЎвЂЎР С‘РЎвЂљРЎРЉ WARP", "СЂСџвЂќТ‘ Turn WARP off") if enabled else _txt("СЂСџСџСћ Р вЂ™Р С”Р В»РЎР‹РЎвЂЎР С‘РЎвЂљРЎРЉ WARP", "СЂСџСџСћ Turn WARP on"),
            callback_data=f"{cb_prefix}_off" if enabled else f"{cb_prefix}_on",
        )
    )
    builder.row(InlineKeyboardButton(text=_txt("СЂСџвЂќвЂ WARP+ Р С”Р В»РЎР‹РЎвЂЎ", "СЂСџвЂќвЂ WARP+ key"), callback_data=f"{cb_prefix}_set_key"))
    if key_set:
        builder.row(InlineKeyboardButton(text=_txt("СЂСџвЂ”вЂ Р Р€Р Т‘Р В°Р В»Р С‘РЎвЂљРЎРЉ Р С”Р В»РЎР‹РЎвЂЎ", "СЂСџвЂ”вЂ Clear key"), callback_data=f"{cb_prefix}_clear_key"))
    builder.row(InlineKeyboardButton(text=_txt("СЂСџвЂќвЂћ Р С›Р В±Р Р…Р С•Р Р†Р С‘РЎвЂљРЎРЉ РЎРѓРЎвЂљР В°РЎвЂљРЎС“РЎРѓ", "СЂСџвЂќвЂћ Refresh status"), callback_data=f"{cb_prefix}_menu"))
    builder.row(InlineKeyboardButton(text=_txt("РІВ¬вЂ¦РїС‘РЏ Р СњР В°Р В·Р В°Р Т‘", "РІВ¬вЂ¦РїС‘РЏ Back"), callback_data=back_cb))
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
            _txt("вЏі РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР° РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ", "вЏі Reinstall is running")
            if action == "reinstall"
            else _txt("вЏі РћР±РЅРѕРІР»РµРЅРёРµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ", "вЏі Update is running")
        )
        builder.row(InlineKeyboardButton(text=running_label, callback_data="maint_update_menu"))
    else:
        if updates:
            builder.row(InlineKeyboardButton(text=_txt("в¬†пёЏ РћР±РЅРѕРІРёС‚СЊ", "в¬†пёЏ Update"), callback_data="maint_update_run_menu"))
        builder.row(
            InlineKeyboardButton(
                text=_txt("в™»пёЏ РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРёС‚СЊ", "в™»пёЏ Reinstall"),
                callback_data="maint_reinstall_menu",
            )
        )

    if running or job.get("container_name"):
        builder.row(InlineKeyboardButton(text=_txt("рџ“њ Р›РѕРіРё", "рџ“њ Logs"), callback_data="maint_update_logs"))
    if not running and job.get("container_name"):
        builder.row(
            InlineKeyboardButton(
                text=_txt("рџ§№ РћС‡РёСЃС‚РёС‚СЊ РґР¶РѕР±", "рџ§№ Cleanup job"),
                callback_data="maint_update_cleanup",
            )
        )
    builder.row(
        InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="menu_maintenance"),
    )
    return builder.as_markup()


def _kb_update_run_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_txt("в¬†пёЏ РћР±РЅРѕРІРёС‚СЊ + backup", "в¬†пёЏ Update + backup"),
            callback_data="maint_update_latest_backup",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_txt("вљ пёЏ РћР±РЅРѕРІРёС‚СЊ Р±РµР· backup", "вљ пёЏ Update without backup"),
            callback_data="maint_update_latest_nobackup_prompt",
        )
    )
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="maint_update_menu"))
    return builder.as_markup()


def _kb_confirm_nobackup(*, confirm_cb: str, back_cb: str = "maint_update_menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_txt("вњ… РџРѕРґС‚РІРµСЂРґРёС‚СЊ", "вњ… Confirm"), callback_data=confirm_cb))
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data=back_cb))
    return builder.as_markup()


def _kb_reinstall_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_txt("в™»пёЏ РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРёС‚СЊ + backup", "в™»пёЏ Reinstall + backup"),
            callback_data="maint_reinstall_cur_backup",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_txt("рџ§№ РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРёС‚СЊ Р±РµР· backup", "рџ§№ Reinstall without backup"),
            callback_data="maint_reinstall_cur_nobackup_prompt",
        )
    )
    builder.row(InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="maint_update_menu"))
    return builder.as_markup()


def _render_update_text(info: dict) -> str:
    git = info.get("git", {})
    job = info.get("job", {})

    version = git.get("current_version") or "-"
    branch = git.get("current_branch", "-")
    commit = git.get("current_commit", "-")
    current_tag = git.get("current_tag") or "вЂ”"
    latest_tag = git.get("latest_tag") or "вЂ”"
    remote_commit = git.get("remote_branch_commit") or "вЂ”"

    upd_tag = "вњ… yes" if git.get("update_available_tag") else "вќЊ no"
    action = str(job.get("action") or "update").lower()
    mode = str(job.get("mode") or "preserve").lower()
    action_label = "update" if action == "update" else "reinstall"
    if _is_ru():
        upd_tag = "вњ… РґР°" if git.get("update_available_tag") else "вќЊ РЅРµС‚"
        action_label = "РѕР±РЅРѕРІР»РµРЅРёРµ" if action == "update" else "РїРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР°"
    if action == "reinstall":
        if _is_ru():
            action_label = "С‡РёСЃС‚Р°СЏ РїРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР°" if mode == "clean" else "РїРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР° (СЃ СЃРѕС…СЂР°РЅРµРЅРёРµРј)"
        else:
            action_label = "clean reinstall" if mode == "clean" else "reinstall (keep data)"

    status = job.get("status") or ("running" if job.get("running") else "idle")
    exit_code = job.get("exit_code")
    exit_line = f"exit code: {exit_code}" if exit_code is not None else "exit code: вЂ”"
    if _is_ru():
        exit_line = f"РєРѕРґ Р·Р°РІРµСЂС€РµРЅРёСЏ: {exit_code}" if exit_code is not None else "РєРѕРґ Р·Р°РІРµСЂС€РµРЅРёСЏ: вЂ”"

    text = (
        f"в¬†пёЏ <b>{_txt('РћР±РЅРѕРІР»РµРЅРёСЏ', 'Updates')}</b>\n\n"
        f"вЂў {_txt('Р’РµСЂСЃРёСЏ', 'Version')}: <code>{escape(str(version))}</code>\n"
        f"вЂў {_txt('РўРµРєСѓС‰Р°СЏ РІРµС‚РєР°', 'Current branch')}: <code>{escape(str(branch))}</code>\n"
        f"вЂў {_txt('РўРµРєСѓС‰РёР№ РєРѕРјРјРёС‚', 'Current commit')}: <code>{escape(str(commit))}</code>\n"
        f"вЂў {_txt('РўРµРєСѓС‰РёР№ С‚РµРі', 'Current tag')}: <code>{escape(str(current_tag))}</code>\n"
        f"вЂў {_txt('РџРѕСЃР»РµРґРЅРёР№ С‚РµРі', 'Latest tag')}: <code>{escape(str(latest_tag))}</code>\n"
        f"вЂў {_txt('origin/РІРµС‚РєР°', 'origin/branch')}: <code>{escape(str(remote_commit))}</code>\n\n"
        f"вЂў {_txt('РќРѕРІС‹Р№ С‚РµРі РґРѕСЃС‚СѓРїРµРЅ', 'New tag available')}: <b>{upd_tag}</b>\n\n"
        f"вЂў {_txt('РўРёРї Р·Р°РґР°С‡Рё', 'Job action')}: <code>{escape(action_label)}</code>\n"
        f"вЂў {_txt('РЎС‚Р°С‚СѓСЃ РґР¶РѕР±Р°', 'Job status')}: <code>{escape(str(status))}</code>\n"
        f"вЂў {exit_line}\n"
    )
    git_error = (git.get("git_error") or "").strip()
    if git_error:
        text += f"\nвљ пёЏ <b>git:</b>\n<pre>{escape(git_error[-700:])}</pre>"
    error = (job.get("error") or "").strip()
    if error:
        text += f"\nвљ пёЏ <b>{_txt('РћС€РёР±РєР° РґР¶РѕР±Р°', 'Job error')}:</b>\n<pre>{escape(error[-700:])}</pre>"
    return text


@router.callback_query(F.data == "menu_maintenance")
async def cb_maint_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        status = await maintenance_api.status()
        backup_hours = int(status["backup"]["auto_hours"] or 0)
        clean_hours = int(status["logs"]["auto_clean_hours"] or 0)
        text = (
            f"рџ”§ <b>{_txt('РћР±СЃР»СѓР¶РёРІР°РЅРёРµ', 'Maintenance')}</b>\n\n"
            f"вЂў {_txt('Backup', 'Backup')}: <b>{_schedule_label(backup_hours)}</b>"
            f" ({_txt('СЃР»РµРґСѓСЋС‰РёР№', 'next')}: {status['backup']['next_at'] or 'вЂ”'})\n"
            f"вЂў {_txt('РћС‡РёСЃС‚РєР° Р»РѕРіРѕРІ', 'Log cleanup')}: <b>{_schedule_label(clean_hours)}</b>"
            f" ({_txt('СЃР»РµРґСѓСЋС‰Р°СЏ', 'next')}: {status['logs']['next_clean_at'] or 'вЂ”'})\n"
            f"вЂў {_txt('Р—Р°Р±Р»РѕРєРёСЂРѕРІР°РЅРЅС‹Рµ IP', 'Banned IPs')}: <b>{status['ip_ban']['count']}</b>"
        )
        kb = _kb_main(status)
    except APIError as exc:
        text = f"вќЊ {exc.detail}"
        kb = kb_back("main_menu")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "maint_backup_menu")
async def cb_backup_menu(cq: CallbackQuery):
    await cq.answer()
    try:
        status = await maintenance_api.status()
        backup_hours = int(status.get("backup", {}).get("auto_hours", 0) or 0)
        text = (
            f"рџ’ѕ <b>{_txt('Backup', 'Backup')}</b>\n\n"
            f"вЂў {_txt('РРЅС‚РµСЂРІР°Р»', 'Interval')}: <b>{_schedule_label(backup_hours)}</b>\n"
            f"вЂў {_txt('РЎР»РµРґСѓСЋС‰РёР№ Р·Р°РїСѓСЃРє', 'Next run')}: <code>{status.get('backup', {}).get('next_at') or 'вЂ”'}</code>\n\n"
            f"{_txt('Р’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ РЅРёР¶Рµ.', 'Choose an action below.')}"
        )
        kb = _kb_backup_menu(status)
    except APIError as exc:
        text = f"вќЊ {exc.detail}"
        kb = kb_back("menu_maintenance")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "maint_logs_root")
async def cb_logs_root(cq: CallbackQuery):
    await cq.answer()
    try:
        status = await maintenance_api.status()
        clean_hours = int(status.get("logs", {}).get("auto_clean_hours", 0) or 0)
        ban_cnt = int(status.get("ip_ban", {}).get("count", 0) or 0)
        text = (
            f"рџ“‹ <b>{_txt('Р›РѕРіРё', 'Logs')}</b>\n\n"
            f"вЂў {_txt('РђРІС‚Рѕ-РѕС‡РёСЃС‚РєР°', 'Auto cleanup')}: <b>{_schedule_label(clean_hours)}</b>\n"
            f"вЂў IP Ban: <b>{ban_cnt}</b>\n\n"
            f"{_txt('Р’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ РЅРёР¶Рµ.', 'Choose an action below.')}"
        )
        kb = _kb_logs_root(status)
    except APIError as exc:
        text = f"вќЊ {exc.detail}"
        kb = kb_back("menu_maintenance")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "maint_backup_now")
async def cb_backup_now(cq: CallbackQuery):
    await cq.answer(_txt("РЎРѕР·РґР°СЋ backupвЂ¦", "Creating backupвЂ¦"))
    try:
        pkg = await maintenance_api.backup_download_package()
        payload = pkg.get("content") or b""
        from datetime import datetime

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        archive = BufferedInputFile(payload, filename=f"backup_{ts}.zip")
        await cq.message.answer_document(
            archive,
            caption=_txt("рџ’ѕ <b>Backup РіРѕС‚РѕРІ</b>", "рџ’ѕ <b>Backup ready</b>"),
            parse_mode="HTML",
        )
        await cq.message.answer(
            _txt("вњ… Backup РѕС‚РїСЂР°РІР»РµРЅ!", "вњ… Backup sent!"),
            reply_markup=kb_back("maint_backup_menu"),
        )
    except APIError as exc:
        await cq.message.answer(f"вќЊ {escape(exc.detail)}", reply_markup=kb_back("maint_backup_menu"), parse_mode="HTML")
    except Exception as exc:
        await cq.message.answer(f"вќЊ {escape(str(exc))}", reply_markup=kb_back("maint_backup_menu"), parse_mode="HTML")


@router.callback_query(F.data == "maint_restore_zip")
async def cb_restore_zip(cq: CallbackQuery, state: FSMContext):
    await state.set_state(RestoreFSM.archive)
    await state.update_data(restore_file_id=None, restore_name=None)
    await cq.message.answer(
        _txt(
            "в™»пёЏ <b>Restore РёР· ZIP</b>\n\n"
            "РћС‚РїСЂР°РІСЊС‚Рµ ZIP-Р°СЂС…РёРІ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ РєР°Рє С„Р°Р№Р».\n"
            "РџРѕСЃР»Рµ Р·Р°РіСЂСѓР·РєРё СЏ РїРѕРїСЂРѕС€Сѓ С„РёРЅР°Р»СЊРЅРѕРµ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ РїРµСЂРµРґ Р·Р°РїСѓСЃРєРѕРј restore.\n\n"
            "вљ пёЏ Restore РїРµСЂРµСЃРѕР·РґР°С‘С‚ СЃС‚РµРє, РїРѕСЌС‚РѕРјСѓ Р±РѕС‚ Рё Web UI РјРѕРіСѓС‚ РѕС‚РєР»СЋС‡РёС‚СЊСЃСЏ РЅР° 30-60 СЃРµРєСѓРЅРґ.",
            "в™»пёЏ <b>Restore from ZIP</b>\n\n"
            "Send the recovery ZIP archive as a file.\n"
            "After upload, I will ask for final confirmation before restore starts.\n\n"
            "вљ пёЏ Restore recreates the stack, so the bot and Web UI may disconnect for 30-60 seconds.",
        ),
        parse_mode="HTML",
        reply_markup=kb_back("maint_backup_menu"),
    )
    await cq.answer()


@router.message(RestoreFSM.archive, F.document)
async def fsm_restore_zip_uploaded(msg: Message, state: FSMContext):
    doc = msg.document
    name = doc.file_name or ""
    if not name.lower().endswith(".zip"):
        await msg.answer(
            _txt("вќЊ РћС‚РїСЂР°РІСЊС‚Рµ Р°СЂС…РёРІ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ <b>.zip</b>.", "вќЊ Send a <b>.zip</b> recovery archive."),
            parse_mode="HTML",
            reply_markup=kb_back("maint_backup_menu"),
        )
        return

    await state.set_state(RestoreFSM.confirm)
    await state.update_data(restore_file_id=doc.file_id, restore_name=name)
    await msg.answer(
        _txt(
            "вљ пёЏ <b>Р“РѕС‚РѕРІРѕ Рє restore</b>\n\n"
            f"РђСЂС…РёРІ: <code>{name}</code>\n"
            "РЎРЅР°С‡Р°Р»Р° Р±СѓРґРµС‚ СЃРѕР·РґР°РЅ Р·Р°С‰РёС‚РЅС‹Р№ backup.\n"
            "Р—Р°С‚РµРј С‚РµРєСѓС‰РёР№ СЃС‚РµРє Р±СѓРґРµС‚ РїРµСЂРµСЃРѕР·РґР°РЅ РёР· СЌС‚РѕРіРѕ Р°СЂС…РёРІР°.\n\n"
            "РќР°Р¶РјРёС‚Рµ <b>РќР°С‡Р°С‚СЊ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёРµ</b>, С‡С‚РѕР±С‹ РїСЂРѕРґРѕР»Р¶РёС‚СЊ.",
            "вљ пёЏ <b>Ready to restore</b>\n\n"
            f"Archive: <code>{name}</code>\n"
            "A safety backup will be created first.\n"
            "Then the current stack will be recreated from this archive.\n\n"
            "Press <b>Start restore</b> to continue.",
        ),
        parse_mode="HTML",
        reply_markup=_kb_restore_confirm(),
    )


@router.message(RestoreFSM.archive)
async def fsm_restore_zip_waiting(msg: Message):
    await msg.answer(
        _txt("рџ“Ћ РћС‚РїСЂР°РІСЊС‚Рµ ZIP-Р°СЂС…РёРІ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ РєР°Рє С„Р°Р№Р».", "рџ“Ћ Send the recovery ZIP archive as a file."),
        reply_markup=kb_back("maint_backup_menu"),
    )


@router.callback_query(RestoreFSM.confirm, F.data == "maint_restore_confirm")
async def cb_restore_confirm(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("restore_file_id")
    name = data.get("restore_name") or "backup.zip"
    if not file_id:
        await state.clear()
        await cq.message.answer(
            _txt("вќЊ РЎРµСЃСЃРёСЏ restore РёСЃС‚РµРєР»Р°.", "вќЊ Restore session expired."),
            reply_markup=kb_back("maint_backup_menu"),
        )
        await cq.answer()
        return

    await cq.answer(_txt("Р—Р°РїСѓСЃРєР°СЋ restoreвЂ¦", "Starting restoreвЂ¦"))
    await cq.message.edit_text(
        _txt(
            "вЏі <b>Р—Р°РїСѓСЃРє restore...</b>\n\n"
            "РЎРєР°С‡РёРІР°СЋ Р°СЂС…РёРІ Рё СЃС‚Р°РІР»СЋ Р·Р°РґР°С‡Сѓ РІРѕСЃСЃС‚Р°РЅРѕРІР»РµРЅРёСЏ.\n"
            "Р‘РѕС‚ Рё Web UI РјРѕРіСѓС‚ РІСЂРµРјРµРЅРЅРѕ РѕС‚РєР»СЋС‡РёС‚СЊСЃСЏ.",
            "вЏі <b>Starting restore...</b>\n\n"
            "Downloading the archive and scheduling the restore job.\n"
            "The bot and Web UI may disconnect shortly.",
        ),
        parse_mode="HTML",
    )

    try:
        remote_file = await cq.bot.get_file(file_id)
        payload = (await cq.bot.download_file(remote_file.file_path)).read()
        result = await maintenance_api.restore(name, payload, create_safety_backup=True)
        await state.clear()

        lines = [
            _txt("вњ… <b>Restore Р·Р°РїСѓС‰РµРЅ</b>", "вњ… <b>Restore started</b>"),
            "",
            _txt(f"РђСЂС…РёРІ: <code>{name}</code>", f"Archive: <code>{name}</code>"),
            _txt("РџРѕРґРѕР¶РґРёС‚Рµ 30-60 СЃРµРєСѓРЅРґ, Р·Р°С‚РµРј СЃРЅРѕРІР° РѕС‚РєСЂРѕР№С‚Рµ Р±РѕС‚Р° РёР»Рё Web UI.", "Wait 30-60 seconds, then reopen the bot or Web UI."),
        ]
        if result.get("safety_backup_path"):
            lines.append(_txt(f"Р—Р°С‰РёС‚РЅС‹Р№ backup: <code>{result['safety_backup_path']}</code>", f"Safety backup: <code>{result['safety_backup_path']}</code>"))
        if result.get("restore_log_path"):
            lines.append(_txt(f"Р›РѕРі restore: <code>{result['restore_log_path']}</code>", f"Restore log: <code>{result['restore_log_path']}</code>"))

        await cq.message.answer(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=kb_back("maint_backup_menu"),
        )
    except APIError as exc:
        await state.clear()
        await cq.message.answer(f"вќЊ {exc.detail}", reply_markup=kb_back("maint_backup_menu"))
    except Exception as exc:
        await state.clear()
        await cq.message.answer(f"вќЊ {exc}", reply_markup=kb_back("maint_backup_menu"))


@router.callback_query(F.data == "maint_backup_interval")
async def cb_backup_interval_menu(cq: CallbackQuery):
    try:
        status = await maintenance_api.status()
        current = status.get("backup", {}).get("auto_hours", 0)
    except APIError:
        current = 0
    await cq.message.edit_text(
        _txt(
            "вЏ± <b>РРЅС‚РµСЂРІР°Р» Р°РІС‚Рѕ-backup</b>\n\nBackup Р±СѓРґРµС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РѕС‚РїСЂР°РІР»СЏС‚СЊСЃСЏ РІСЃРµРј Telegram-Р°РґРјРёРЅР°Рј.",
            "вЏ± <b>Auto-backup interval</b>\n\nBackup will be sent to all Telegram admins automatically.",
        ),
        reply_markup=_kb_intervals(_BACKUP_INTERVALS, "maint_bset", current, back_cb="maint_backup_menu"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("maint_bset_"))
async def cb_backup_set(cq: CallbackQuery):
    hours = int(cq.data.split("_")[-1])
    try:
        await maintenance_api.set_backup_interval(hours)
        label = _schedule_label(hours)
        await cq.answer(_txt(f"вњ… РђРІС‚Рѕ-backup: {label}", f"вњ… Auto-backup: {label}"))
        status = await maintenance_api.status()
        await cq.message.edit_text(
            f"рџ’ѕ <b>{_txt('Backup', 'Backup')}</b>\n\n"
            f"вЂў {_txt('РРЅС‚РµСЂРІР°Р»', 'Interval')}: <b>{_schedule_label(int(status.get('backup', {}).get('auto_hours', 0) or 0))}</b>\n"
            f"вЂў {_txt('РЎР»РµРґСѓСЋС‰РёР№ Р·Р°РїСѓСЃРє', 'Next run')}: <code>{status.get('backup', {}).get('next_at') or 'вЂ”'}</code>",
            reply_markup=_kb_backup_menu(status),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"вќЊ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_logs_menu")
async def cb_logs_menu(cq: CallbackQuery):
    try:
        data = await maintenance_api.logs_list()
        files = data.get("files", [])
        text = _txt(
            "рџ“‹ <b>Р›РѕРіРё Nginx</b>\n\nРќР°Р¶РјРёС‚Рµ в¬‡пёЏ РґР»СЏ СЃРєР°С‡РёРІР°РЅРёСЏ, рџ—‘ РґР»СЏ РѕС‡РёСЃС‚РєРё.",
            "рџ“‹ <b>Nginx logs</b>\n\nClick в¬‡пёЏ to download, рџ—‘ to clear.",
        )
        kb = _kb_logs(files)
    except APIError as exc:
        text = f"вќЊ {exc.detail}"
        kb = kb_back("maint_logs_root")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("maint_log_dl_"))
async def cb_log_download(cq: CallbackQuery):
    name = cq.data[len("maint_log_dl_"):]
    await cq.answer(_txt("РЎРєР°С‡РёРІР°СЋвЂ¦", "DownloadingвЂ¦"))
    try:
        content = await maintenance_api.log_download(name)
        if content:
            file = BufferedInputFile(content if isinstance(content, bytes) else content.encode(), filename=name)
            await cq.message.answer_document(file, caption=f"рџ“‹ <code>{name}</code>", parse_mode="HTML")
        else:
            await cq.message.answer(_txt("вљ пёЏ Р¤Р°Р№Р» Р»РѕРіР° РїСѓСЃС‚.", "вљ пёЏ Log file is empty"))
    except APIError as exc:
        await cq.message.answer(f"вќЊ {exc.detail}")


@router.callback_query(F.data.startswith("maint_log_clr_"))
async def cb_log_clear(cq: CallbackQuery):
    name = cq.data[len("maint_log_clr_"):]
    try:
        if name == "all":
            result = await maintenance_api.log_clear_all()
            cleared = result.get("cleared", [])
            await cq.answer(_txt(f"вњ… РћС‡РёС‰РµРЅРѕ С„Р°Р№Р»РѕРІ: {len(cleared)}", f"вњ… Cleared {len(cleared)} files"))
        else:
            await maintenance_api.log_clear_one(name)
            await cq.answer(_txt(f"вњ… {name} РѕС‡РёС‰РµРЅ", f"вњ… {name} cleared"))
        data = await maintenance_api.logs_list()
        await cq.message.edit_text(
            _txt("рџ“‹ <b>Р›РѕРіРё Nginx</b>", "рџ“‹ <b>Nginx logs</b>"),
            reply_markup=_kb_logs(data.get("files", [])),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"вќЊ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_clean_interval")
async def cb_clean_interval_menu(cq: CallbackQuery):
    try:
        status = await maintenance_api.status()
        current = status.get("logs", {}).get("auto_clean_hours", 0)
    except APIError:
        current = 0
    await cq.message.edit_text(
        _txt(
            "вЏ± <b>РРЅС‚РµСЂРІР°Р» Р°РІС‚Рѕ-РѕС‡РёСЃС‚РєРё Р»РѕРіРѕРІ</b>\n\nР›РѕРіРё РґРѕСЃС‚СѓРїР°/РѕС€РёР±РѕРє Nginx Р±СѓРґСѓС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РѕС‡РёС‰Р°С‚СЊСЃСЏ.",
            "вЏ± <b>Auto log cleanup interval</b>\n\nNginx access/error logs will be truncated automatically.",
        ),
        reply_markup=_kb_intervals(_CLEAN_INTERVALS, "maint_cset", current, back_cb="maint_logs_root"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("maint_cset_"))
async def cb_clean_set(cq: CallbackQuery):
    hours = int(cq.data.split("_")[-1])
    try:
        await maintenance_api.set_log_clean_interval(hours)
        label = _schedule_label(hours)
        await cq.answer(_txt(f"вњ… РђРІС‚Рѕ-РѕС‡РёСЃС‚РєР°: {label}", f"вњ… Auto cleanup: {label}"))
        status = await maintenance_api.status()
        await cq.message.edit_text(
            f"рџ“‹ <b>{_txt('Р›РѕРіРё', 'Logs')}</b>\n\n"
            f"вЂў {_txt('РђРІС‚Рѕ-РѕС‡РёСЃС‚РєР°', 'Auto cleanup')}: <b>{_schedule_label(int(status.get('logs', {}).get('auto_clean_hours', 0) or 0))}</b>\n"
            f"вЂў IP Ban: <b>{int(status.get('ip_ban', {}).get('count', 0) or 0)}</b>",
            reply_markup=_kb_logs_root(status),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"вќЊ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_ipban_menu")
async def cb_ipban_menu(cq: CallbackQuery):
    try:
        data = await maintenance_api.ip_ban_list()
        banned = data.get("banned", [])
        text = _txt(
            f"рџљ« <b>РЎРїРёСЃРѕРє IP Ban</b> ({len(banned)} IP)\n\nРќР°Р¶РјРёС‚Рµ РЅР° IP, С‡С‚РѕР±С‹ СЂР°Р·Р±Р»РѕРєРёСЂРѕРІР°С‚СЊ.",
            f"рџљ« <b>IP Ban list</b> ({len(banned)} IPs)\n\nClick IP to unban.",
        )
        kb = _kb_ipban(banned)
    except APIError as exc:
        text = f"вќЊ {exc.detail}"
        kb = kb_back("maint_logs_root")
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "maint_ban_manual")
async def cb_ban_manual(cq: CallbackQuery, state: FSMContext):
    await state.set_state(IpBanFSM.manual_ip)
    await cq.message.answer(
        _txt(
            "вњЏпёЏ Р’РІРµРґРёС‚Рµ IP РґР»СЏ Р±Р»РѕРєРёСЂРѕРІРєРё (РЅР°РїСЂРёРјРµСЂ, <code>1.2.3.4</code>):",
            "вњЏпёЏ Enter IP address to ban (e.g. <code>1.2.3.4</code>):",
        ),
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
            _txt(
                f"вњ… <code>{ip}</code> Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅ\nNginx РїРµСЂРµР·Р°РіСЂСѓР¶РµРЅ: {'вњ…' if result.get('nginx_reloaded') else 'вљ пёЏ'}",
                f"вњ… <code>{ip}</code> banned\nNginx reloaded: {'вњ…' if result.get('nginx_reloaded') else 'вљ пёЏ'}",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("maint_ipban_menu"),
        )
    except APIError as exc:
        await msg.answer(f"вќЊ {exc.detail}", reply_markup=kb_back("maint_ipban_menu"))


@router.callback_query(F.data.startswith("maint_unban_"))
async def cb_unban(cq: CallbackQuery):
    ip = cq.data[len("maint_unban_"):]
    try:
        await maintenance_api.ip_ban_remove(ip)
        await cq.answer(_txt(f"вњ… {ip} СЂР°Р·Р±Р»РѕРєРёСЂРѕРІР°РЅ", f"вњ… {ip} unbanned"))
        data = await maintenance_api.ip_ban_list()
        banned = data.get("banned", [])
        await cq.message.edit_text(
            _txt(
                f"рџљ« <b>РЎРїРёСЃРѕРє IP Ban</b> ({len(banned)} IP)",
                f"рџљ« <b>IP Ban list</b> ({len(banned)} IPs)",
            ),
            reply_markup=_kb_ipban(banned),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"вќЊ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_analyze")
async def cb_analyze(cq: CallbackQuery):
    await cq.answer(_txt("РђРЅР°Р»РёР·РёСЂСѓСЋ Р»РѕРіРёвЂ¦", "Analyzing logsвЂ¦"))
    try:
        data = await maintenance_api.ip_ban_analyze()
        suspicious = data.get("suspicious", [])
        if not suspicious:
            await cq.message.answer(
                _txt("вњ… РџРѕРґРѕР·СЂРёС‚РµР»СЊРЅС‹Рµ IP РІ Р»РѕРіР°С… РЅРµ РЅР°Р№РґРµРЅС‹.", "вњ… No suspicious IPs found in logs."),
                reply_markup=kb_back("maint_ipban_menu"),
            )
            return

        lines = [f"вЂў <code>{entry['ip']}</code> вЂ” {entry['reason']}" for entry in suspicious[:20]]
        text = _txt(
            f"рџ”Ќ <b>РџРѕРґРѕР·СЂРёС‚РµР»СЊРЅС‹Рµ IP ({len(suspicious)}):</b>\n",
            f"рџ”Ќ <b>Suspicious IPs ({len(suspicious)}):</b>\n",
        ) + "\n".join(lines)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=_txt(f"рџљ« Р—Р°Р±Р»РѕРєРёСЂРѕРІР°С‚СЊ РІСЃРµ {len(suspicious)} IP", f"рџљ« Ban all {len(suspicious)} IPs"), callback_data="maint_ban_all_analyzed")],
                [InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="maint_ipban_menu")],
            ]
        )
        await cq.message.answer(text, reply_markup=kb, parse_mode="HTML")
    except APIError as exc:
        await cq.message.answer(f"вќЊ {exc.detail}", reply_markup=kb_back("maint_ipban_menu"))


@router.callback_query(F.data == "maint_ban_all_analyzed")
async def cb_ban_all_analyzed(cq: CallbackQuery):
    await cq.answer(_txt("Р‘Р»РѕРєРёСЂСѓСЋвЂ¦", "BanningвЂ¦"))
    try:
        result = await maintenance_api.ip_ban_all_analyzed()
        count = result.get("banned", 0)
        await cq.message.edit_text(
            _txt(
                f"вњ… Р—Р°Р±Р»РѕРєРёСЂРѕРІР°РЅРѕ <b>{count}</b> IP. Nginx РїРµСЂРµР·Р°РіСЂСѓР¶РµРЅ.",
                f"вњ… Banned <b>{count}</b> IPs. Nginx reloaded.",
            ),
            reply_markup=kb_back("maint_ipban_menu"),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"вќЊ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_clear_auto")
async def cb_clear_auto_bans(cq: CallbackQuery):
    try:
        result = await maintenance_api.ip_ban_clear_auto()
        count = result.get("removed", 0)
        await cq.answer(_txt(f"вњ… РЈРґР°Р»РµРЅРѕ Р°РІС‚Рѕ-Р±Р°РЅРѕРІ: {count}", f"вњ… Removed {count} auto-bans"))
        data = await maintenance_api.ip_ban_list()
        await cq.message.edit_text(
            _txt(
                f"рџљ« <b>РЎРїРёСЃРѕРє IP Ban</b> ({len(data.get('banned', []))} IP)",
                f"рџљ« <b>IP Ban list</b> ({len(data.get('banned', []))} IPs)",
            ),
            reply_markup=_kb_ipban(data.get("banned", [])),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"вќЊ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_windows")
async def cb_windows_menu(cq: CallbackQuery):
    try:
        status = await maintenance_api.windows_binaries_status()
        version = status.get("sing_box_version", "?")
        sing_box = "вњ…" if status.get("sing_box_cached") else "вќЊ"
        winsw = "вњ…" if status.get("winsw_cached") else "вќЊ"
        ready = status.get("ready", False)
        state_text = _txt(
            "вњ… Р“РѕС‚РѕРІРѕ вЂ” РєР»РёРµРЅС‚С‹ РјРѕРіСѓС‚ СЃРєР°С‡РёРІР°С‚СЊ ZIP",
            "вњ… Ready вЂ” clients can download ZIP",
        ) if ready else _txt(
            "вљ пёЏ Р‘РёРЅР°СЂРЅРёРєРё РµС‰С‘ РЅРµ Р·Р°РіСЂСѓР¶РµРЅС‹",
            "вљ пёЏ Binaries not downloaded yet",
        )
        await cq.message.edit_text(
            f"рџЄџ <b>{_txt('Р‘РёРЅР°СЂРЅРёРєРё Windows Service', 'Windows Service Binaries')}</b>\n\n"
            f"{sing_box} sing-box.exe (v{version})\n"
            f"{winsw} winsw3.exe\n\n"
            f"{state_text}\n\n"
            + _txt(
                "РџРѕСЃР»Рµ Р·Р°РіСЂСѓР·РєРё РєР°Р¶РґС‹Р№ РєР»РёРµРЅС‚ СЃРјРѕР¶РµС‚ РїРѕР»СѓС‡РёС‚СЊ РіРѕС‚РѕРІС‹Р№ ZIP-Р°СЂС…РёРІ "
                "(sing-box.exe + winsw3.exe + scripts + XML) С‡РµСЂРµР· Sub URL.",
                "After downloading, each client can get a ready-to-use ZIP archive "
                "(sing-box.exe + winsw3.exe + scripts + XML) via Sub URL.",
            ),
            reply_markup=_kb_windows(status),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.answer(f"вќЊ {exc.detail}", show_alert=True)


@router.callback_query(F.data == "maint_win_prefetch")
async def cb_win_prefetch(cq: CallbackQuery):
    await cq.answer(_txt("вЏі РЎРєР°С‡РёРІР°СЋвЂ¦ СЌС‚Рѕ РјРѕР¶РµС‚ Р·Р°РЅСЏС‚СЊ 1-2 РјРёРЅСѓС‚С‹", "вЏі DownloadingвЂ¦ this may take 1-2 minutes"))
    await cq.message.edit_text(
        _txt(
            "вЏі <b>РЎРєР°С‡РёРІР°СЋ Р±РёРЅР°СЂРЅРёРєРё Windows...</b>\n\n"
            "вЂў sing-box.exe (Windows AMD64)\n"
            "вЂў winsw3.exe\n\n"
            "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїРѕРґРѕР¶РґРёС‚Рµ, РѕР±С‹С‡РЅРѕ СЌС‚Рѕ Р·Р°РЅРёРјР°РµС‚ 1-2 РјРёРЅСѓС‚С‹.",
            "вЏі <b>Downloading Windows binaries...</b>\n\n"
            "вЂў sing-box.exe (Windows AMD64)\n"
            "вЂў winsw3.exe\n\n"
            "Please wait, this usually takes 1-2 minutes.",
        ),
        parse_mode="HTML",
    )
    try:
        await maintenance_api.prefetch_windows_binaries()
        status = await maintenance_api.windows_binaries_status()
        await cq.message.edit_text(
            _txt(
                "вњ… <b>Р‘РёРЅР°СЂРЅРёРєРё Windows Р·Р°РіСЂСѓР¶РµРЅС‹!</b>\n\n"
                "РўРµРїРµСЂСЊ РєР»РёРµРЅС‚С‹ РјРѕРіСѓС‚ СЃРєР°С‡РёРІР°С‚СЊ ZIP Windows Service С‡РµСЂРµР· СЃРІРѕР№ Sub URL.",
                "вњ… <b>Windows binaries downloaded!</b>\n\n"
                "Clients can now download the Windows Service ZIP from their Sub URL.",
            ),
            reply_markup=_kb_windows(status),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.edit_text(
            _txt(
                f"вќЊ <b>РћС€РёР±РєР° Р·Р°РіСЂСѓР·РєРё</b>\n\n{exc.detail}\n\n"
                "РџСЂРѕРІРµСЂСЊС‚Рµ, С‡С‚Рѕ Сѓ СЃРµСЂРІРµСЂР° РµСЃС‚СЊ РґРѕСЃС‚СѓРї РІ РёРЅС‚РµСЂРЅРµС‚, Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ СЃРЅРѕРІР°.",
                f"вќЊ <b>Download failed</b>\n\n{exc.detail}\n\n"
                "Check that the server has internet access and try again.",
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text=_txt("рџ”„ РџРѕРІС‚РѕСЂРёС‚СЊ", "рџ”„ Retry"), callback_data="maint_win_prefetch"),
                        InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="maint_windows"),
                    ]
                ]
            ),
            parse_mode="HTML",
        )


# РІвЂќР‚РІвЂќР‚РІвЂќР‚ Updates РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚РІвЂќР‚

@router.callback_query(F.data.in_(("menu_warp", "menu_warp_menu")))
async def cb_warp_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.answer()
    try:
        data = await maintenance_api.warp_status()
        await cq.message.edit_text(
            _render_warp_text(data),
            reply_markup=_kb_warp(data),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.edit_text(
            f"вќЊ {escape(exc.detail)}",
            reply_markup=kb_back("main_menu"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu_warp_on")
async def cb_warp_on(cq: CallbackQuery):
    await cq.answer(_txt("Р—Р°РїСѓСЃРєР°СЋ WARP...", "Starting WARP..."))
    try:
        data = await maintenance_api.warp_on()
        await cq.message.edit_text(
            _render_warp_text(data),
            reply_markup=_kb_warp(data),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.answer(
            f"вќЊ {escape(exc.detail)}",
            parse_mode="HTML",
            reply_markup=kb_back("menu_warp"),
        )

@router.callback_query(F.data == "menu_warp_off")
async def cb_warp_off(cq: CallbackQuery):
    await cq.answer(_txt("Р’С‹РєР»СЋС‡Р°СЋ WARP...", "Stopping WARP..."))
    try:
        data = await maintenance_api.warp_off()
        await cq.message.edit_text(
            _render_warp_text(data),
            reply_markup=_kb_warp(data),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.answer(
            f"вќЊ {escape(exc.detail)}",
            parse_mode="HTML",
            reply_markup=kb_back("menu_warp"),
        )

@router.callback_query(F.data == "menu_warp_set_key")
async def cb_warp_set_key(cq: CallbackQuery, state: FSMContext):
    menu_cb = "menu_warp"
    await state.set_state(WarpFSM.license_key)
    await state.update_data(warp_menu_cb=menu_cb)
    await cq.answer()
    await cq.message.answer(
        _txt(
            "<b>WARP+ РєР»СЋС‡</b>\n\n"
            "РћС‚РїСЂР°РІСЊС‚Рµ РєР»СЋС‡ РІ С„РѕСЂРјР°С‚Рµ <code>XXXX-XXXX-XXXX</code>.\n"
            "Р•СЃР»Рё WARP РІРєР»СЋС‡РµРЅ, РєР»СЋС‡ РїСЂРёРјРµРЅРёС‚СЃСЏ СЃСЂР°Р·Сѓ.",
            "<b>WARP+ key</b>\n\n"
            "Send your key in format <code>XXXX-XXXX-XXXX</code>.\n"
            "If WARP is enabled, it will be applied immediately.",
        ),
        parse_mode="HTML",
        reply_markup=kb_back(menu_cb),
    )

@router.message(WarpFSM.license_key)
async def fsm_warp_key(msg: Message, state: FSMContext):
    data = await state.get_data()
    menu_cb = str(data.get("warp_menu_cb") or "menu_warp")
    key = (msg.text or "").strip()
    await state.clear()
    if not key:
        await msg.answer(
            _txt("вќЊ РљР»СЋС‡ РЅРµ РјРѕР¶РµС‚ Р±С‹С‚СЊ РїСѓСЃС‚С‹Рј.", "вќЊ Key cannot be empty."),
            reply_markup=kb_back(menu_cb),
        )
        return
    try:
        result = await maintenance_api.warp_set_key(key)
        applied = bool(result.get("applied_now"))
        await msg.answer(
            _txt(
                "вњ… РљР»СЋС‡ СЃРѕС…СЂР°РЅРµРЅ." + (" РџСЂРёРјРµРЅРµРЅ СЃСЂР°Р·Сѓ." if applied else ""),
                "вњ… Key saved." + (" Applied now." if applied else ""),
            ),
            reply_markup=kb_back(menu_cb),
        )
    except APIError as exc:
        await msg.answer(
            f"вќЊ {escape(exc.detail)}",
            parse_mode="HTML",
            reply_markup=kb_back(menu_cb),
        )

@router.callback_query(F.data == "menu_warp_clear_key")
async def cb_warp_clear_key(cq: CallbackQuery):
    await cq.answer(_txt("РЈРґР°Р»СЏСЋ РєР»СЋС‡...", "Clearing key..."))
    try:
        data = await maintenance_api.warp_clear_key()
        await cq.message.edit_text(
            _render_warp_text(data),
            reply_markup=_kb_warp(data),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.answer(
            f"вќЊ {escape(exc.detail)}",
            parse_mode="HTML",
            reply_markup=kb_back("menu_warp"),
        )

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
            f"вќЊ {escape(exc.detail)}",
            reply_markup=kb_back("menu_maintenance"),
            parse_mode="HTML",
        )


async def _run_update(cq: CallbackQuery, *, with_backup: bool) -> None:
    await cq.answer(_txt("Р—Р°РїСѓСЃРєР°СЋ РѕР±РЅРѕРІР»РµРЅРёРµвЂ¦", "Starting updateвЂ¦"))
    try:
        info = await maintenance_api.update_info()
        if info.get("job", {}).get("running"):
            await cq.message.answer(
                _txt("вЏі РЈР¶Рµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ РґСЂСѓРіР°СЏ Р·Р°РґР°С‡Р° РѕР±СЃР»СѓР¶РёРІР°РЅРёСЏ.", "вЏі A maintenance job is already running."),
                reply_markup=kb_back("maint_update_menu"),
            )
            return
        git = info.get("git", {})
        has_updates = bool(git.get("update_available_tag"))
        if not has_updates:
            await cq.message.answer(
                _txt("в„№пёЏ РќРѕРІС‹С… РѕР±РЅРѕРІР»РµРЅРёР№ РЅРµ РѕР±РЅР°СЂСѓР¶РµРЅРѕ.", "в„№пёЏ No updates detected."),
                reply_markup=kb_back("maint_update_menu"),
            )
            return

        backup_path = ""
        if with_backup:
            detected_path = await _send_preflight_backup(cq, reason_ru="РѕР±РЅРѕРІР»РµРЅРёРµРј", reason_en="update")
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
            f"вњ… РћР±РЅРѕРІР»РµРЅРёРµ Р·Р°РїСѓС‰РµРЅРѕ.\nРўРµРі: <code>{escape(str(target_ref))}</code>\n"
            "Backup+restore РІРєР»СЋС‡РµРЅС‹.\n"
            "РџСЂРѕРІРµСЂСЊС‚Рµ Р»РѕРіРё С‡РµСЂРµР· 10-20 СЃРµРєСѓРЅРґ."
            if with_backup
            else
            f"вњ… РћР±РЅРѕРІР»РµРЅРёРµ Р·Р°РїСѓС‰РµРЅРѕ.\nРўРµРі: <code>{escape(str(target_ref))}</code>\n"
            "Р—Р°РїСѓС‰РµРЅРѕ Р±РµР· backup/restore.\n"
            "РџСЂРѕРІРµСЂСЊС‚Рµ Р»РѕРіРё С‡РµСЂРµР· 10-20 СЃРµРєСѓРЅРґ."
        )
        en_msg = (
            f"вњ… Update started.\nTag: <code>{escape(str(target_ref))}</code>\n"
            "Backup+restore enabled.\n"
            "Check logs in 10-20 seconds."
            if with_backup
            else
            f"вњ… Update started.\nTag: <code>{escape(str(target_ref))}</code>\n"
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
        await cq.message.answer(f"вќЊ {escape(exc.detail)}", reply_markup=kb_back("maint_update_menu"), parse_mode="HTML")


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
            f"\n\n<b>Р§С‚Рѕ РЅРѕРІРѕРіРѕ РІ {escape(latest_tag)}:</b>\n<pre>{escape(notes[-1800:])}</pre>",
            f"\n\n<b>What's new in {escape(latest_tag)}:</b>\n<pre>{escape(notes[-1800:])}</pre>",
        )
    else:
        notes_block = _txt(
            f"\n\n<b>Р§С‚Рѕ РЅРѕРІРѕРіРѕ РІ {escape(latest_tag)}:</b>\n<i>РћРїРёСЃР°РЅРёРµ СЂРµР»РёР·Р° РЅРµ СѓРєР°Р·Р°РЅРѕ.</i>",
            f"\n\n<b>What's new in {escape(latest_tag)}:</b>\n<i>No release notes provided.</i>",
        )

    text = _txt(
        "в¬†пёЏ <b>РћР±РЅРѕРІР»РµРЅРёРµ</b>\n\n"
        "Р”РѕСЃС‚СѓРїРЅС‹ РґРІР° СЂРµР¶РёРјР°:\n"
        "вЂў РЎ backup: РѕС‚РїСЂР°РІР»СЏРµРј Р°СЂС…РёРІ, Р·Р°С‚РµРј update Рё restore.\n"
        "вЂў Р‘РµР· backup: update Р±РµР· restore (С‚СЂРµР±СѓРµС‚ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ).",
        "в¬†пёЏ <b>Update</b>\n\n"
        "Two modes are available:\n"
        "вЂў With backup: send archive, then update and restore.\n"
        "вЂў Without backup: update without restore (requires confirmation).",
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
            "вљ пёЏ <b>РћР±РЅРѕРІР»РµРЅРёРµ Р±РµР· backup</b>\n\n"
            "Р’ СЌС‚РѕРј СЂРµР¶РёРјРµ РЅРµ Р±СѓРґРµС‚ СЃРѕР·РґР°РЅ Р°СЂС…РёРІ Рё РЅРµ Р±СѓРґРµС‚ restore.\n"
            "РџСЂРѕРґРѕР»Р¶РёС‚СЊ?",
            "вљ пёЏ <b>Update without backup</b>\n\n"
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
            "в™»пёЏ <b>РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР°</b>\n\n"
            "РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР° РІСЃРµРіРґР° РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ РЅР° С‚РµРєСѓС‰СѓСЋ СѓСЃС‚Р°РЅРѕРІР»РµРЅРЅСѓСЋ РІРµСЂСЃРёСЋ.\n"
            "Р’С‹Р±РµСЂРёС‚Рµ СЂРµР¶РёРј:\n"
            "вЂў C backup: СЃРЅР°С‡Р°Р»Р° РѕС‚РїСЂР°РІРёС‚СЊ backup, Р·Р°С‚РµРј hard reinstall Рё restore.\n"
            "вЂў Р‘РµР· backup: С‚РѕР»СЊРєРѕ hard reinstall Р±РµР· restore.",
            "в™»пёЏ <b>Reinstall</b>\n\n"
            "Reinstall always runs for the currently installed version.\n"
            "Choose mode:\n"
            "вЂў With backup: send backup first, then hard reinstall and restore.\n"
            "вЂў Without backup: hard reinstall only, no restore.",
        ),
        reply_markup=_kb_reinstall_menu(),
        parse_mode="HTML",
    )


async def _run_reinstall(cq: CallbackQuery, *, with_backup: bool) -> None:
    await cq.answer(
        _txt("Р—Р°РїСѓСЃРєР°СЋ РїРµСЂРµСѓСЃС‚Р°РЅРѕРІРєСѓвЂ¦", "Starting reinstallвЂ¦")
    )
    try:
        info = await maintenance_api.update_info()
        if info.get("job", {}).get("running"):
            await cq.message.answer(
                _txt("вЏі РЈР¶Рµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ РґСЂСѓРіР°СЏ Р·Р°РґР°С‡Р° РѕР±СЃР»СѓР¶РёРІР°РЅРёСЏ.", "вЏі A maintenance job is already running."),
                reply_markup=kb_back("maint_update_menu"),
            )
            return

        backup_path = ""
        if with_backup:
            detected_path = await _send_preflight_backup(cq, reason_ru="РїРµСЂРµСѓСЃС‚Р°РЅРѕРІРєРѕР№", reason_en="reinstall")
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
            "вњ… РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР° Р·Р°РїСѓС‰РµРЅР° (current version).\n"
            "Р‘РѕС‚/РІРµР± РјРѕРіСѓС‚ Р±С‹С‚СЊ РЅРµРґРѕСЃС‚СѓРїРЅС‹ 30-60 СЃРµРєСѓРЅРґ.\n"
            "Backup+restore РІРєР»СЋС‡РµРЅС‹."
            if with_backup
            else
            "вњ… РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР° Р·Р°РїСѓС‰РµРЅР° (current version).\n"
            "Р‘РѕС‚/РІРµР± РјРѕРіСѓС‚ Р±С‹С‚СЊ РЅРµРґРѕСЃС‚СѓРїРЅС‹ 30-60 СЃРµРєСѓРЅРґ.\n"
            "Р—Р°РїСѓС‰РµРЅРѕ Р±РµР· backup/restore."
        )
        en_msg = (
            "вњ… Reinstall started (current version).\n"
            "Bot/Web may be unavailable for 30-60 seconds.\n"
            "Backup+restore enabled."
            if with_backup
            else
            "вњ… Reinstall started (current version).\n"
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
        await cq.message.answer(f"вќЊ {escape(exc.detail)}", reply_markup=kb_back("maint_update_menu"), parse_mode="HTML")


@router.callback_query(F.data == "maint_reinstall_cur_backup")
async def cb_reinstall_cur_backup(cq: CallbackQuery):
    await _run_reinstall(cq, with_backup=True)


@router.callback_query(F.data == "maint_reinstall_cur_nobackup_prompt")
async def cb_reinstall_cur_nobackup_prompt(cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        _txt(
            "вљ пёЏ <b>РџРµСЂРµСѓСЃС‚Р°РЅРѕРІРєР° Р±РµР· backup</b>\n\n"
            "Р’ СЌС‚РѕРј СЂРµР¶РёРјРµ РЅРµ Р±СѓРґРµС‚ СЃРѕР·РґР°РЅ Р°СЂС…РёРІ Рё РЅРµ Р±СѓРґРµС‚ restore.\n"
            "РџСЂРѕРґРѕР»Р¶РёС‚СЊ?",
            "вљ пёЏ <b>Reinstall without backup</b>\n\n"
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
            logs = _txt("Р›РѕРіРё РїРѕРєР° РїСѓСЃС‚С‹Рµ.", "No logs yet.")
        status = data.get("status", "unknown")
        running = data.get("running", False)
        action = str(data.get("action") or "update").lower()
        if action == "reinstall":
            title = _txt("рџ“њ Р›РѕРіРё РїРµСЂРµСѓСЃС‚Р°РЅРѕРІРєРё", "рџ“њ Reinstall logs")
        else:
            title = _txt("рџ“њ Р›РѕРіРё РѕР±РЅРѕРІР»РµРЅРёСЏ", "рџ“њ Update logs")
        state_line = (
            _txt("вЏі Р’С‹РїРѕР»РЅСЏРµС‚СЃСЏ", "вЏі Running")
            if running
            else _txt(f"вњ… Р—Р°РІРµСЂС€РµРЅРѕ ({status})", f"вњ… Finished ({status})")
        )
        text = f"{title}\n{state_line}\n\n<pre>{escape(logs[-3500:])}</pre>"
        await cq.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=_txt("рџ”„ РћР±РЅРѕРІРёС‚СЊ Р»РѕРіРё", "рџ”„ Refresh logs"), callback_data="maint_update_logs")],
                    [InlineKeyboardButton(text=_txt("в¬…пёЏ РќР°Р·Р°Рґ", "в¬…пёЏ Back"), callback_data="maint_update_menu")],
                ]
            ),
        )
    except APIError as exc:
        await cq.message.answer(f"вќЊ {escape(exc.detail)}", reply_markup=kb_back("maint_update_menu"), parse_mode="HTML")


@router.callback_query(F.data == "maint_update_cleanup")
async def cb_update_cleanup(cq: CallbackQuery):
    await cq.answer(_txt("РћС‡РёС‰Р°СЋвЂ¦", "CleaningвЂ¦"))
    try:
        await maintenance_api.update_cleanup()
        info = await maintenance_api.update_info()
        await cq.message.edit_text(
            _render_update_text(info),
            reply_markup=_kb_update_menu(info),
            parse_mode="HTML",
        )
    except APIError as exc:
        await cq.message.answer(f"вќЊ {escape(exc.detail)}", reply_markup=kb_back("maint_update_menu"), parse_mode="HTML")



