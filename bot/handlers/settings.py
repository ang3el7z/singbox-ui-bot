"""
Bot settings: timezone, language, domain, system info.
Admin management is in admin.py — linked from here.
"""
import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from api.routers.settings_router import get_runtime
from bot.api_client import settings_api, APIError
from bot.keyboards.main import kb_back

router = Router()


class DomainFSM(StatesGroup):
    waiting = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en

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


def _kb_settings_menu(tz: str, lang: str, domain: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"🌍 {_txt('Домен', 'Domain')}: {domain or '—'}",
        callback_data="settings_domain",
    ))
    builder.row(InlineKeyboardButton(
        text=f"🕐 {_txt('Часовой пояс', 'Timezone')}: {tz}",
        callback_data="settings_tz_groups",
    ))
    lang_icon = "🇷🇺" if lang == "ru" else "🇬🇧"
    builder.row(InlineKeyboardButton(
        text=f"{lang_icon} {_txt('Язык', 'Language')}: {lang}",
        callback_data="settings_lang_choose",
    ))
    builder.row(InlineKeyboardButton(text=_txt("👑 Управление админами", "👑 Manage admins"), callback_data="menu_admin"))
    builder.row(InlineKeyboardButton(text=_txt("ℹ️ Системная информация", "ℹ️ System info"), callback_data="settings_system"))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu"))
    return builder.as_markup()


def _kb_tz_groups() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for group in _TZ_GROUPS:
        builder.row(InlineKeyboardButton(text=group, callback_data=f"settings_tzg_{group}"))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_settings"))
    return builder.as_markup()


def _kb_tz_list(group: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, iana in _TZ_GROUPS.get(group, []):
        builder.row(InlineKeyboardButton(text=label, callback_data=f"settings_tz_{iana}"))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="settings_tz_groups"))
    return builder.as_markup()


def _kb_lang() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский",  callback_data="settings_lang_ru"),
         InlineKeyboardButton(text="🇬🇧 English",  callback_data="settings_lang_en")],
        [InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_settings")],
    ])


# ─── Entry point ──────────────────────────────────────────────────────────────

async def _settings_menu(cq: CallbackQuery):
    s = await settings_api.get_all()
    tz     = s.get("tz",       "UTC")
    lang   = s.get("bot_lang", "ru")
    domain = s.get("domain",   "—")
    await cq.message.edit_text(
        _txt("⚙️ <b>Настройки</b>", "⚙️ <b>Settings</b>"),
        reply_markup=_kb_settings_menu(tz, lang, domain),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu_settings")
async def cb_settings_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await _settings_menu(cq)


# ─── Timezone — group → list → save (no manual typing) ────────────────────────

@router.callback_query(F.data == "settings_tz_groups")
async def cb_tz_groups(cq: CallbackQuery):
    await cq.message.edit_text(
        _txt("🕐 <b>Выберите регион часового пояса:</b>", "🕐 <b>Select timezone region:</b>"),
        reply_markup=_kb_tz_groups(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("settings_tzg_"))
async def cb_tz_group(cq: CallbackQuery):
    group = cq.data[len("settings_tzg_"):]
    if group not in _TZ_GROUPS:
        await cq.answer(_txt("Неизвестная группа", "Unknown group"), show_alert=True)
        return
    await cq.message.edit_text(
        _txt(f"🕐 <b>{group}</b>\nВыберите часовой пояс:", f"🕐 <b>{group}</b>\nSelect timezone:"),
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
        await _settings_menu(cq)
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── Language — two-button choice ─────────────────────────────────────────────

@router.callback_query(F.data == "settings_lang_choose")
async def cb_lang_choose(cq: CallbackQuery):
    await cq.message.edit_text(
        _txt("🌐 <b>Выберите язык бота:</b>", "🌐 <b>Select bot language:</b>"),
        reply_markup=_kb_lang(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.in_({"settings_lang_ru", "settings_lang_en"}))
async def cb_lang_set(cq: CallbackQuery):
    lang = "ru" if cq.data == "settings_lang_ru" else "en"
    try:
        r = await settings_api.set("bot_lang", lang)
        await cq.answer(_txt(f"✅ Язык: {r['value']}", f"✅ Language: {r['value']}"))
        await _settings_menu(cq)
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


# ─── Domain ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_domain")
async def cb_domain_prompt(cq: CallbackQuery, state: FSMContext):
    await state.set_state(DomainFSM.waiting)
    try:
        cur = (await settings_api.get("domain")).get("value", "")
    except APIError:
        cur = ""
    await cq.message.answer(
        _txt(
            f"🌍 <b>Смена домена</b>\n\n"
            f"Текущий: <code>{cur}</code>\n\n"
            "Введите новый домен (например <code>example.com</code>):\n"
            "<i>Конфиг Nginx будет пересоздан автоматически.\n"
            "Если домен изменился, перевыпустите SSL отдельно.</i>",
            f"🌍 <b>Change domain</b>\n\n"
            f"Current: <code>{cur}</code>\n\n"
            "Enter new domain (e.g. <code>example.com</code>):\n"
            "<i>Nginx config will be regenerated automatically.\n"
            "Re-issue SSL separately if the domain actually changed.</i>",
        ),
        parse_mode="HTML",
        reply_markup=kb_back("menu_settings"),
    )
    await cq.answer()


@router.message(DomainFSM.waiting)
async def fsm_domain_set(msg: Message, state: FSMContext):
    await state.clear()
    domain = msg.text.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    try:
        r = await settings_api.set("domain", domain)
        note = r.get("note", "")
        await msg.answer(
            _txt(
                f"✅ Домен обновлён: <code>{r['value']}</code>\n"
                f"<i>{note}</i>",
                f"✅ Domain updated: <code>{r['value']}</code>\n"
                f"<i>{note}</i>",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("menu_settings"),
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_settings"))


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
        (
            "ℹ️ <b>Системная информация</b>\n\n"
            "<b>Автозапуск после перезагрузки сервера:</b>\n"
            "✅ Все контейнеры: <code>restart: unless-stopped</code>\n"
            "   → Контейнеры поднимаются автоматически.\n\n"
            "<b>Автообновление SSL:</b>\n"
            f"{'✅' if cron_ok else '⚠️'} Certbot cron: {'активен' if cron_ok else 'не найден'}\n"
            f"{'✅' if hook_ok else '⚠️'} Renewal hook: {'активен' if hook_ok else 'не найден'}\n\n"
            "<b>После ручного обновления сертификата:</b>\n"
            "  🌐 Nginx → ⚙️ Настроить"
        )
        if _is_ru()
        else (
            "ℹ️ <b>System Info</b>\n\n"
            "<b>Auto-restart on server reboot:</b>\n"
            "✅ All containers: <code>restart: unless-stopped</code>\n"
            "   → Containers start automatically after server reboot.\n\n"
            "<b>Auto SSL renewal:</b>\n"
            f"{'✅' if cron_ok else '⚠️'} Certbot cron: {'active' if cron_ok else 'not found'}\n"
            f"{'✅' if hook_ok else '⚠️'} Renewal hook: {'active' if hook_ok else 'not found'}\n\n"
            "<b>After manual cert renewal:</b>\n"
            "  🌐 Nginx → ⚙️ Configure"
        )
    )
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_settings"))
