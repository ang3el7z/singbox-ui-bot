"""
Bot settings: timezone, language, system info (auto-restart / SSL renewal).
Admin management is in admin.py — linked from here too.
"""
import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.api_client import settings_api, admin_api, APIError
from bot.keyboards.main import kb_back

router = Router()

# Common timezones for quick-pick
_TZ_PRESETS = [
    ("🇷🇺 Moscow",   "Europe/Moscow"),
    ("🇺🇦 Kyiv",     "Europe/Kyiv"),
    ("🇰🇿 Almaty",   "Asia/Almaty"),
    ("🌍 UTC",       "UTC"),
    ("🇩🇪 Berlin",   "Europe/Berlin"),
    ("🇬🇧 London",   "Europe/London"),
    ("🇺🇸 New York", "America/New_York"),
    ("🇺🇸 LA",       "America/Los_Angeles"),
    ("🇨🇳 Shanghai", "Asia/Shanghai"),
    ("✏️ Custom...",  "__custom__"),
]


class SettingsFSM(StatesGroup):
    tz_custom = State()


# ─── Keyboards ────────────────────────────────────────────────────────────────

def _kb_settings_menu(tz: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🕐 Timezone: {tz}",
        callback_data="settings_tz_menu",
    ))
    lang_icon = "🇷🇺" if lang == "ru" else "🇬🇧"
    builder.row(InlineKeyboardButton(
        text=f"{lang_icon} Language: {lang}",
        callback_data="settings_lang_toggle",
    ))
    builder.row(
        InlineKeyboardButton(text="👑 Manage admins", callback_data="menu_admin"),
    )
    builder.row(
        InlineKeyboardButton(text="ℹ️ System info",   callback_data="settings_system"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu"))
    return builder.as_markup()


def _kb_tz_presets() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, tz in _TZ_PRESETS:
        builder.row(InlineKeyboardButton(text=label, callback_data=f"settings_tz_set_{tz}"))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="menu_settings"))
    return builder.as_markup()


# ─── Handlers ─────────────────────────────────────────────────────────────────

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
        "⚙️ <b>Settings</b>\n\nConfigure timezone, language, and admins.",
        reply_markup=_kb_settings_menu(tz, lang),
        parse_mode="HTML",
    )


# ── Timezone ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_tz_menu")
async def cb_tz_menu(cq: CallbackQuery):
    await cq.message.edit_text(
        "🕐 <b>Select timezone</b>\n\nChoose a preset or enter a custom IANA timezone string.",
        reply_markup=_kb_tz_presets(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("settings_tz_set_"))
async def cb_tz_set(cq: CallbackQuery, state: FSMContext):
    tz = cq.data[len("settings_tz_set_"):]
    if tz == "__custom__":
        await state.set_state(SettingsFSM.tz_custom)
        await cq.message.answer(
            "✏️ Enter IANA timezone string (e.g. <code>Europe/Moscow</code>, <code>Asia/Almaty</code>):",
            parse_mode="HTML",
            reply_markup=kb_back("settings_tz_menu"),
        )
        await cq.answer()
        return
    await _save_tz(cq, state, tz)


@router.message(SettingsFSM.tz_custom)
async def fsm_tz_custom(msg: Message, state: FSMContext):
    tz = msg.text.strip()
    await state.clear()
    try:
        r = await settings_api.set("tz", tz)
        await msg.answer(
            f"✅ Timezone set to <code>{r['value']}</code>",
            parse_mode="HTML",
            reply_markup=kb_back("menu_settings"),
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_settings"))


async def _save_tz(cq: CallbackQuery, state: FSMContext, tz: str):
    await state.clear()
    try:
        r = await settings_api.set("tz", tz)
        await cq.answer(f"✅ Timezone: {r['value']}")
        s = await settings_api.get_all()
        await cq.message.edit_text(
            "⚙️ <b>Settings</b>\n\nConfigure timezone, language, and admins.",
            reply_markup=_kb_settings_menu(s.get("tz", "UTC"), s.get("bot_lang", "ru")),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ── Language ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_lang_toggle")
async def cb_lang_toggle(cq: CallbackQuery):
    try:
        current = (await settings_api.get("bot_lang"))["value"]
        new_lang = "en" if current == "ru" else "ru"
        r = await settings_api.set("bot_lang", new_lang)
        await cq.answer(f"✅ Language: {r['value']}")
        s = await settings_api.get_all()
        await cq.message.edit_text(
            "⚙️ <b>Settings</b>\n\nConfigure timezone, language, and admins.",
            reply_markup=_kb_settings_menu(s.get("tz", "UTC"), s.get("bot_lang", "ru")),
            parse_mode="HTML",
        )
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ── System info ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_system")
async def cb_system_info(cq: CallbackQuery):
    await cq.answer()

    # Check certbot cron
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

    # Check renewal hook
    hook_ok = False
    try:
        import os
        hook_ok = os.path.exists("/etc/letsencrypt/renewal-hooks/deploy/copy-to-singbox.sh")
    except Exception:
        pass

    text = (
        "ℹ️ <b>System Info</b>\n\n"
        "<b>Auto-restart on server reboot:</b>\n"
        "✅ All containers use <code>restart: unless-stopped</code>\n"
        "   → If the server reboots, all containers start automatically.\n\n"
        "<b>Auto SSL renewal:</b>\n"
        f"{'✅' if cron_ok else '⚠️'} Certbot cron job: {'active' if cron_ok else 'not found'}\n"
        f"{'✅' if hook_ok else '⚠️'} Renewal copy hook: {'active' if hook_ok else 'not found'}\n"
        "   → Run <b>Nginx → Configure & Reload</b> after manual renewal.\n\n"
        "<b>To add cron manually:</b>\n"
        "<pre>crontab -e\n"
        "0 3 * * * certbot renew --quiet</pre>"
    )
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_settings"))
