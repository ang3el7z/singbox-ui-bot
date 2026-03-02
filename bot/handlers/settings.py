"""
Bot settings: timezone, language, system info (auto-restart / SSL renewal).
Admin management is in admin.py — linked from here too.
All inputs are selection-based to prevent typos.
"""
import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.api_client import settings_api, APIError
from bot.keyboards.main import kb_back

router = Router()

# ─── Timezone catalog ─────────────────────────────────────────────────────────
# Grouped: (display_label, iana_value)
_TZ_GROUPS = {
    "🇷🇺 Russia / СНГ": [
        ("Moscow (UTC+3)",       "Europe/Moscow"),
        ("Kyiv (UTC+2/+3)",      "Europe/Kyiv"),
        ("Minsk (UTC+3)",        "Europe/Minsk"),
        ("Almaty (UTC+5)",       "Asia/Almaty"),
        ("Tashkent (UTC+5)",     "Asia/Tashkent"),
        ("Baku (UTC+4)",         "Asia/Baku"),
        ("Tbilisi (UTC+4)",      "Asia/Tbilisi"),
        ("Yerevan (UTC+4)",      "Asia/Yerevan"),
        ("Novosibirsk (UTC+7)",  "Asia/Novosibirsk"),
        ("Krasnoyarsk (UTC+7)",  "Asia/Krasnoyarsk"),
        ("Irkutsk (UTC+8)",      "Asia/Irkutsk"),
        ("Vladivostok (UTC+10)", "Asia/Vladivostok"),
    ],
    "🌍 Europe": [
        ("Berlin (UTC+1/+2)",    "Europe/Berlin"),
        ("London (UTC+0/+1)",    "Europe/London"),
        ("Paris (UTC+1/+2)",     "Europe/Paris"),
        ("Amsterdam (UTC+1/+2)", "Europe/Amsterdam"),
        ("Warsaw (UTC+1/+2)",    "Europe/Warsaw"),
    ],
    "🌎 Americas": [
        ("New York (UTC-5/-4)",      "America/New_York"),
        ("Los Angeles (UTC-8/-7)",   "America/Los_Angeles"),
        ("Chicago (UTC-6/-5)",       "America/Chicago"),
        ("Toronto (UTC-5/-4)",       "America/Toronto"),
        ("São Paulo (UTC-3)",        "America/Sao_Paulo"),
    ],
    "🌏 Asia / Pacific": [
        ("Shanghai (UTC+8)",     "Asia/Shanghai"),
        ("Tokyo (UTC+9)",        "Asia/Tokyo"),
        ("Seoul (UTC+9)",        "Asia/Seoul"),
        ("Dubai (UTC+4)",        "Asia/Dubai"),
        ("Singapore (UTC+8)",    "Asia/Singapore"),
        ("Bangkok (UTC+7)",      "Asia/Bangkok"),
        ("Kolkata (UTC+5:30)",   "Asia/Kolkata"),
        ("Sydney (UTC+10/+11)",  "Australia/Sydney"),
    ],
    "🌐 Universal": [
        ("UTC",                  "UTC"),
    ],
}


def _kb_settings_menu(tz: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🕐 Timezone: {tz}",
        callback_data="settings_tz_groups",
    ))
    lang_icon = "🇷🇺" if lang == "ru" else "🇬🇧"
    builder.row(InlineKeyboardButton(
        text=f"{lang_icon} Language: {lang}",
        callback_data="settings_lang_choose",
    ))
    builder.row(InlineKeyboardButton(text="👑 Manage admins", callback_data="menu_admin"))
    builder.row(InlineKeyboardButton(text="ℹ️ System info",   callback_data="settings_system"))
    builder.row(InlineKeyboardButton(text="⬅️ Back",           callback_data="main_menu"))
    return builder.as_markup()


def _kb_tz_groups() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group in _TZ_GROUPS:
        builder.row(InlineKeyboardButton(text=group, callback_data=f"settings_tzg_{group}"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu_settings"))
    return builder.as_markup()


def _kb_tz_list(group: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, iana in _TZ_GROUPS.get(group, []):
        builder.row(InlineKeyboardButton(text=label, callback_data=f"settings_tz_{iana}"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="settings_tz_groups"))
    return builder.as_markup()


def _kb_lang() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Russian",  callback_data="settings_lang_ru"),
         InlineKeyboardButton(text="🇬🇧 English",  callback_data="settings_lang_en")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_settings")],
    ])


# ─── Entry point ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_settings")
async def cb_settings_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        s = await settings_api.get_all()
        tz   = s.get("tz", "UTC")
        lang = s.get("bot_lang", "ru")
    except APIError:
        tz, lang = "UTC", "ru"
    await cq.message.edit_text(
        "⚙️ <b>Settings</b>",
        reply_markup=_kb_settings_menu(tz, lang),
        parse_mode="HTML",
    )


# ─── Timezone — group → list → save (no manual typing) ────────────────────────

@router.callback_query(F.data == "settings_tz_groups")
async def cb_tz_groups(cq: CallbackQuery):
    await cq.message.edit_text(
        "🕐 <b>Select timezone region:</b>",
        reply_markup=_kb_tz_groups(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("settings_tzg_"))
async def cb_tz_group(cq: CallbackQuery):
    group = cq.data[len("settings_tzg_"):]
    if group not in _TZ_GROUPS:
        await cq.answer("Unknown group", show_alert=True)
        return
    await cq.message.edit_text(
        f"🕐 <b>{group}</b>\nSelect timezone:",
        reply_markup=_kb_tz_list(group),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("settings_tz_") & ~F.data.startswith("settings_tzg_"))
async def cb_tz_set(cq: CallbackQuery):
    # callback: settings_tz_<iana>  (iana may contain slashes — fine for callback_data)
    iana = cq.data[len("settings_tz_"):]
    try:
        r = await settings_api.set("tz", iana)
        await cq.answer(f"✅ {r['value']}")
        s = await settings_api.get_all()
        await cq.message.edit_text(
            "⚙️ <b>Settings</b>",
            reply_markup=_kb_settings_menu(s.get("tz", "UTC"), s.get("bot_lang", "ru")),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── Language — two-button choice ─────────────────────────────────────────────

@router.callback_query(F.data == "settings_lang_choose")
async def cb_lang_choose(cq: CallbackQuery):
    await cq.message.edit_text(
        "🌐 <b>Select bot language:</b>",
        reply_markup=_kb_lang(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.in_({"settings_lang_ru", "settings_lang_en"}))
async def cb_lang_set(cq: CallbackQuery):
    lang = "ru" if cq.data == "settings_lang_ru" else "en"
    try:
        r = await settings_api.set("bot_lang", lang)
        await cq.answer(f"✅ Language: {r['value']}")
        s = await settings_api.get_all()
        await cq.message.edit_text(
            "⚙️ <b>Settings</b>",
            reply_markup=_kb_settings_menu(s.get("tz", "UTC"), s.get("bot_lang", "ru")),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── System info ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_system")
async def cb_system_info(cq: CallbackQuery):
    await cq.answer()

    cron_ok = False
    try:
        proc = await asyncio.create_subprocess_exec(
            "crontab", "-l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        cron_ok = b"certbot renew" in stdout
    except Exception:
        pass

    import os
    hook_ok = os.path.exists("/etc/letsencrypt/renewal-hooks/deploy/copy-to-singbox.sh")

    text = (
        "ℹ️ <b>System Info</b>\n\n"
        "<b>Auto-restart on server reboot:</b>\n"
        "✅ All containers: <code>restart: unless-stopped</code>\n"
        "   → Containers start automatically after server reboot.\n\n"
        "<b>Auto SSL renewal:</b>\n"
        f"{'✅' if cron_ok else '⚠️'} Certbot cron: {'active' if cron_ok else 'not found'}\n"
        f"{'✅' if hook_ok else '⚠️'} Renewal hook: {'active' if hook_ok else 'not found'}\n\n"
        "<b>After manual cert renewal:</b>\n"
        "  🌐 Nginx → ⚙️ Configure & Reload"
    )
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_settings"))
