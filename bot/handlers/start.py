import asyncio
import httpx
import time
from datetime import datetime
from html import escape

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.api_client import APIError, maintenance_api, nginx_api, settings_api
from bot.keyboards.main import kb_main_menu

router = Router()
_MENU_GIT_CACHE: dict[str, object] = {"ts": 0.0, "git": {}}

# ─── Timezone list ────────────────────────────────────────────────────────────

_TIMEZONES = [
    "Europe/Moscow",    "Europe/Kyiv",      "Europe/Minsk",
    "Europe/Berlin",    "Europe/London",    "Europe/Paris",
    "Asia/Almaty",      "Asia/Tashkent",    "Asia/Baku",
    "Asia/Tbilisi",     "Asia/Yerevan",     "Asia/Novosibirsk",
    "Asia/Krasnoyarsk", "Asia/Irkutsk",     "Asia/Yakutsk",
    "Asia/Vladivostok", "Asia/Tokyo",       "Asia/Shanghai",
    "America/New_York", "America/Chicago",  "America/Los_Angeles",
    "UTC",
]

_PER_PAGE = 9


def _normalize_domain(raw: str) -> str:
    domain = raw.strip().lower()
    if domain.startswith("https://"):
        domain = domain[len("https://"):]
    elif domain.startswith("http://"):
        domain = domain[len("http://"):]
    return domain.rstrip("/")


# ─── Setup FSM ────────────────────────────────────────────────────────────────

class SetupFSM(StatesGroup):
    language = State()
    timezone = State()
    domain   = State()     # waiting for user to type a custom domain
    domain_menu = State()  # showing the domain options menu


# ─── Keyboards ────────────────────────────────────────────────────────────────

def _kb_lang() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺  Русский", callback_data="setup_lang_ru")],
        [InlineKeyboardButton(text="🇬🇧  English", callback_data="setup_lang_en")],
    ])


def _kb_tz(page: int = 0) -> InlineKeyboardMarkup:
    start = page * _PER_PAGE
    chunk = _TIMEZONES[start : start + _PER_PAGE]
    rows = [
        [InlineKeyboardButton(text=tz, callback_data=f"setup_tz_{tz}")]
        for tz in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"setup_tzp_{page - 1}"))
    if start + _PER_PAGE < len(_TIMEZONES):
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"setup_tzp_{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_domain(ip: str, lang: str) -> InlineKeyboardMarkup:
    nip = ip.replace(".", "-") + ".nip.io"
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔗 Использовать {nip}", callback_data=f"setup_dom_nip")],
            [InlineKeyboardButton(text="✏️ Ввести свой домен",   callback_data="setup_dom_custom")],
            [InlineKeyboardButton(text="⏭️ Пропустить (позже)", callback_data="setup_dom_skip")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔗 Use {nip}", callback_data=f"setup_dom_nip")],
        [InlineKeyboardButton(text="✏️ Enter custom domain",   callback_data="setup_dom_custom")],
        [InlineKeyboardButton(text="⏭️ Skip (configure later)", callback_data="setup_dom_skip")],
    ])


def _format_cert_line_for_main(cert: dict, lang: str) -> str:
    if not cert or not cert.get("exists"):
        return "Сертификат: не выпущен" if lang == "ru" else "Certificate: not issued"

    expires = cert.get("expires_at")
    days_left = cert.get("days_left")
    if isinstance(expires, str):
        try:
            dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if lang == "ru":
                if isinstance(days_left, int):
                    return f"Сертификат: до <code>{dt.strftime('%d.%m.%Y')}</code> ({days_left} дн.)"
                return f"Сертификат: до <code>{dt.strftime('%d.%m.%Y')}</code>"
            if isinstance(days_left, int):
                return f"Certificate: until <code>{dt.strftime('%Y-%m-%d')}</code> ({days_left} days)"
            return f"Certificate: until <code>{dt.strftime('%Y-%m-%d')}</code>"
        except Exception:
            pass

    return "Сертификат: выпущен" if lang == "ru" else "Certificate: issued"


def _build_version_lines(git: dict, lang: str) -> tuple[str, str]:
    current_tag = (git.get("current_tag") or "").strip()
    current_commit = (git.get("current_commit") or "").strip()
    latest_tag = (git.get("latest_tag") or "").strip()
    remote_commit = (git.get("remote_branch_commit") or "").strip()
    has_updates = bool(git.get("update_available_branch")) or bool(git.get("update_available_tag"))

    current_version = current_tag or current_commit or "-"
    version_line = (
        f"Версия: <code>{escape(current_version)}</code>"
        if lang == "ru"
        else f"Version: <code>{escape(current_version)}</code>"
    )

    if not has_updates:
        return version_line, ("Обновлений нет" if lang == "ru" else "No updates detected")

    new_version = latest_tag or remote_commit or "latest"
    update_line = (
        f"Доступно обновление: <code>{escape(new_version)}</code>"
        if lang == "ru"
        else f"Update available: <code>{escape(new_version)}</code>"
    )
    return version_line, update_line


async def _main_menu_text(lang: str) -> str:
    domain = ""
    cert: dict = {}
    git: dict = {}

    try:
        domain_data = await settings_api.get("domain")
        domain = (domain_data.get("value") or "").strip() if isinstance(domain_data, dict) else ""
    except Exception:
        domain = ""

    try:
        nginx_status = await nginx_api.status()
        cert = nginx_status.get("cert") or {}
    except APIError:
        cert = {}

    git = await _get_menu_git_info()

    domain_value = domain or ("не задан" if lang == "ru" else "not set")
    domain_line = (
        f"Домен: <code>{escape(domain_value)}</code>"
        if lang == "ru"
        else f"Domain: <code>{escape(domain_value)}</code>"
    )
    cert_line = _format_cert_line_for_main(cert, lang)
    version_line, update_line = _build_version_lines(git, lang)
    return (
        "<b>Singbox UI Bot</b>\n\n"
        f"{domain_line}\n"
        f"{cert_line}\n"
        f"{version_line}\n"
        f"{update_line}"
    )


async def _get_menu_git_info() -> dict:
    now = time.time()
    cached_ts = float(_MENU_GIT_CACHE.get("ts") or 0.0)
    cached_git = _MENU_GIT_CACHE.get("git")
    if isinstance(cached_git, dict) and cached_git and (now - cached_ts) < 300:
        return cached_git

    try:
        fresh = await asyncio.wait_for(maintenance_api.update_info(refresh_remote=True), timeout=4.0)
        git = fresh.get("git") or {}
        if isinstance(git, dict):
            _MENU_GIT_CACHE["ts"] = now
            _MENU_GIT_CACHE["git"] = git
            return git
    except Exception:
        pass

    if isinstance(cached_git, dict):
        return cached_git
    return {}


# ─── /start and /menu ─────────────────────────────────────────────────────────

@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(msg: Message, state: FSMContext, setup_mode: bool = False):
    if setup_mode:
        await state.set_state(SetupFSM.language)
        await msg.answer(
            "👋 <b>Welcome to Singbox UI Bot!</b>\n"
            "👋 <b>Добро пожаловать в Singbox UI Bot!</b>\n\n"
            "First launch — let's do a quick setup.\n"
            "Первый запуск — давайте настроим систему.\n\n"
            "<b>Step 1 / 3 — Language / Язык:</b>",
            reply_markup=_kb_lang(),
            parse_mode="HTML",
        )
        return

    lang = _get_lang()
    await msg.answer(await _main_menu_text(lang), reply_markup=kb_main_menu(), parse_mode="HTML")


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cq: CallbackQuery):
    lang = _get_lang()
    await cq.message.edit_text(await _main_menu_text(lang), reply_markup=kb_main_menu(), parse_mode="HTML")
    await cq.answer()


# ─── Wizard step 1: language ──────────────────────────────────────────────────

@router.callback_query(SetupFSM.language, F.data.startswith("setup_lang_"))
async def setup_lang(cq: CallbackQuery, state: FSMContext):
    lang = cq.data.rsplit("_", 1)[-1]
    await state.update_data(lang=lang)
    await state.set_state(SetupFSM.timezone)

    text = (
        "✅ Язык: <b>Русский</b>\n\n<b>Шаг 2 / 3 — Часовой пояс:</b>"
        if lang == "ru"
        else "✅ Language: <b>English</b>\n\n<b>Step 2 / 3 — Timezone:</b>"
    )
    await cq.message.edit_text(text, reply_markup=_kb_tz(), parse_mode="HTML")
    await cq.answer()


# ─── Wizard step 2: timezone pagination ──────────────────────────────────────

@router.callback_query(SetupFSM.timezone, F.data.startswith("setup_tzp_"))
async def setup_tz_page(cq: CallbackQuery, state: FSMContext):
    page = int(cq.data.rsplit("_", 1)[-1])
    data = await state.get_data()
    text = "Выберите часовой пояс:" if data.get("lang") == "ru" else "Select your timezone:"
    await cq.message.edit_text(text, reply_markup=_kb_tz(page), parse_mode="HTML")
    await cq.answer()


# ─── Wizard step 2: timezone chosen → go to domain step ─────────────────────

@router.callback_query(SetupFSM.timezone, F.data.startswith("setup_tz_"))
async def setup_tz(cq: CallbackQuery, state: FSMContext):
    tz = cq.data[len("setup_tz_"):]
    await state.update_data(tz=tz)
    await state.set_state(SetupFSM.domain_menu)

    data = await state.get_data()
    lang = data.get("lang", "en")

    # Detect server public IP
    ip = await _get_public_ip()
    await state.update_data(server_ip=ip)

    nip = ip.replace(".", "-") + ".nip.io"
    if lang == "ru":
        text = (
            f"✅ Часовой пояс: <code>{tz}</code>\n\n"
            f"<b>Шаг 3 / 3 — Домен</b>\n\n"
            f"IP сервера: <code>{ip}</code>\n"
            f"Можно использовать автоматический nip.io:\n"
            f"<code>{nip}</code>\n\n"
            f"Или введите свой домен (A-запись должна указывать на этот сервер)."
        )
    else:
        text = (
            f"✅ Timezone: <code>{tz}</code>\n\n"
            f"<b>Step 3 / 3 — Domain</b>\n\n"
            f"Server IP: <code>{ip}</code>\n"
            f"You can use the automatic nip.io address:\n"
            f"<code>{nip}</code>\n\n"
            f"Or enter your own domain (A-record must point to this server)."
        )

    await cq.message.edit_text(text, reply_markup=_kb_domain(ip, lang), parse_mode="HTML")
    await cq.answer()


# ─── Wizard step 3: domain — nip.io ──────────────────────────────────────────

@router.callback_query(SetupFSM.domain_menu, F.data == "setup_dom_nip")
async def setup_dom_nip(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ip = data.get("server_ip", "")
    domain = ip.replace(".", "-") + ".nip.io"
    await _finish_setup(cq, state, domain, issued_ssl=False)


# ─── Wizard step 3: domain — custom ──────────────────────────────────────────

@router.callback_query(SetupFSM.domain_menu, F.data == "setup_dom_custom")
async def setup_dom_custom(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    await state.set_state(SetupFSM.domain)
    text = (
        "Введите ваш домен (например: <code>edge.example.com</code>):"
        if lang == "ru"
        else "Enter your domain (e.g. <code>edge.example.com</code>):"
    )
    await cq.message.edit_text(text, parse_mode="HTML")
    await cq.answer()


@router.message(SetupFSM.domain)
async def setup_dom_input(msg: Message, state: FSMContext):
    domain = _normalize_domain(msg.text)
    data = await state.get_data()
    lang = data.get("lang", "en")

    import re
    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$", domain):
        err = "❌ Неверный формат. Введите ещё раз:" if lang == "ru" else "❌ Invalid format. Try again:"
        await msg.answer(err, parse_mode="HTML")
        return

    await _finish_setup_msg(msg, state, domain, issued_ssl=False)


# ─── Wizard step 3: domain — skip ────────────────────────────────────────────

@router.callback_query(SetupFSM.domain_menu, F.data == "setup_dom_skip")
async def setup_dom_skip(cq: CallbackQuery, state: FSMContext):
    await _finish_setup(cq, state, domain="", issued_ssl=False)


# ─── Finalization helpers ─────────────────────────────────────────────────────

async def _finish_setup(cq: CallbackQuery, state: FSMContext, domain: str, issued_ssl: bool):
    """Called when domain step is completed via callback."""
    data = await state.get_data()
    lang = data.get("lang", "en")
    tz   = data.get("tz", "UTC")

    await _save_setup(cq.from_user.id, cq.from_user.username, lang, tz, domain)
    await state.clear()

    text = _done_text(lang, tz, domain)
    await cq.message.edit_text(text, reply_markup=kb_main_menu(), parse_mode="HTML")
    await cq.answer()

    # Trigger nginx regen if domain was set
    if domain:
        await _apply_domain(domain, lang, cq.message)


async def _finish_setup_msg(msg: Message, state: FSMContext, domain: str, issued_ssl: bool):
    """Called when domain step is completed via text message."""
    data = await state.get_data()
    lang = data.get("lang", "en")
    tz   = data.get("tz", "UTC")

    await _save_setup(msg.from_user.id, msg.from_user.username, lang, tz, domain)
    await state.clear()

    text = _done_text(lang, tz, domain)
    await msg.answer(text, reply_markup=kb_main_menu(), parse_mode="HTML")

    if domain:
        await _apply_domain(domain, lang, msg)


async def _save_setup(tg_id: int, username: str, lang: str, tz: str, domain: str):
    """Persist admin + settings to DB."""
    from api.database import async_session, Admin, AppSetting
    from api.routers.settings_router import _apply_setting_sync

    async with async_session() as session:
        from sqlalchemy import select
        existing = await session.execute(select(Admin).where(Admin.telegram_id == tg_id))
        if not existing.scalar_one_or_none():
            session.add(Admin(telegram_id=tg_id, username=username, added_by=None))

        for key, value in [("bot_lang", lang), ("tz", tz), ("domain", domain)]:
            if value:
                row = await session.get(AppSetting, key)
                if row:
                    row.value = value
                else:
                    session.add(AppSetting(key=key, value=value))

        await session.commit()

    _apply_setting_sync("bot_lang", lang)
    _apply_setting_sync("tz", tz)
    if domain:
        _apply_setting_sync("domain", domain)


async def _apply_domain(domain: str, lang: str, reply_target):
    """Regenerate nginx config after domain is set. Issue SSL hint."""
    try:
        from api.services import nginx_service
        config_text = nginx_service.generate_config(domain=domain)
        nginx_service.write_config(config_text)
        await nginx_service.reload_nginx()

        hint = (
            f"✅ Домен <code>{domain}</code> сохранён.\n"
            f"Nginx обновлён. Теперь выпустите SSL:\n"
            f"⚙️ Настройки → <b>Nginx → Выпустить SSL</b>"
            if lang == "ru"
            else
            f"✅ Domain <code>{domain}</code> saved.\n"
            f"Nginx updated. Now issue SSL:\n"
            f"⚙️ Settings → <b>Nginx → Issue SSL</b>"
        )
    except Exception as e:
        hint = f"⚠️ Nginx reload failed: {e}"

    await reply_target.answer(hint, parse_mode="HTML")


def _done_text(lang: str, tz: str, domain: str) -> str:
    if lang == "ru":
        dom_line = f"  🌐 Домен: <code>{domain}</code>" if domain else "  🌐 Домен: не задан (настройте позже)"
        return (
            f"✅ <b>Настройка завершена!</b>\n\n"
            f"  🌍 Часовой пояс: <code>{tz}</code>\n"
            f"  🗣 Язык: Русский\n"
            f"{dom_line}\n\n"
            f"Вы зарегистрированы как первый администратор. 🎉"
        )
    dom_line = f"  🌐 Domain: <code>{domain}</code>" if domain else "  🌐 Domain: not set (configure later)"
    return (
        f"✅ <b>Setup complete!</b>\n\n"
        f"  🌍 Timezone: <code>{tz}</code>\n"
        f"  🗣 Language: English\n"
        f"{dom_line}\n\n"
        f"You have been registered as the first administrator. 🎉"
    )


# ─── Catch stray text during wizard ──────────────────────────────────────────

@router.message(F.text, SetupFSM.language)
@router.message(F.text, SetupFSM.timezone)
@router.message(F.text, SetupFSM.domain_menu)
async def setup_please_use_buttons(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    await msg.answer(
        "Пожалуйста, используйте кнопки выше." if lang == "ru" else "Please use the buttons above."
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_lang() -> str:
    from api.routers.settings_router import get_runtime
    return get_runtime("bot_lang", "ru")


async def _get_public_ip() -> str:
    """Detect the server's public IPv4 address."""
    services = [
        "https://api.ipify.org",
        "https://api4.my-ip.io/ip",
        "https://ipv4.icanhazip.com",
    ]
    async with httpx.AsyncClient(timeout=5) as client:
        for url in services:
            try:
                r = await client.get(url)
                ip = r.text.strip()
                if ip:
                    return ip
            except Exception:
                continue
    return "0.0.0.0"
