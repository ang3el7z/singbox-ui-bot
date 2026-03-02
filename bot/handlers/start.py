from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.keyboards.main import kb_main_menu

router = Router()

# ─── Timezones list ───────────────────────────────────────────────────────────

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


# ─── Setup FSM ────────────────────────────────────────────────────────────────

class SetupFSM(StatesGroup):
    language = State()
    timezone = State()


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
            "<b>Step 1 / 2 — Language / Язык:</b>",
            reply_markup=_kb_lang(),
            parse_mode="HTML",
        )
        return

    lang = _get_lang()
    await msg.answer(
        "👋 <b>Singbox UI Bot</b>\n\n"
        + ("Выберите раздел:" if lang == "ru" else "Choose a section:"),
        reply_markup=kb_main_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cq: CallbackQuery):
    lang = _get_lang()
    await cq.message.edit_text(
        "👋 <b>Singbox UI Bot</b>\n\n"
        + ("Выберите раздел:" if lang == "ru" else "Choose a section:"),
        reply_markup=kb_main_menu(),
        parse_mode="HTML",
    )
    await cq.answer()


# ─── Setup wizard — step 1: language ─────────────────────────────────────────

@router.callback_query(SetupFSM.language, F.data.startswith("setup_lang_"))
async def setup_lang(cq: CallbackQuery, state: FSMContext):
    lang = cq.data.rsplit("_", 1)[-1]   # "ru" or "en"
    await state.update_data(lang=lang)
    await state.set_state(SetupFSM.timezone)

    if lang == "ru":
        text = "✅ Язык: <b>Русский</b>\n\n<b>Шаг 2 / 2 — Часовой пояс:</b>"
    else:
        text = "✅ Language: <b>English</b>\n\n<b>Step 2 / 2 — Timezone:</b>"

    await cq.message.edit_text(text, reply_markup=_kb_tz(), parse_mode="HTML")
    await cq.answer()


# ─── Setup wizard — step 2: timezone pagination ──────────────────────────────

@router.callback_query(SetupFSM.timezone, F.data.startswith("setup_tzp_"))
async def setup_tz_page(cq: CallbackQuery, state: FSMContext):
    page = int(cq.data.rsplit("_", 1)[-1])
    data = await state.get_data()
    lang = data.get("lang", "en")
    text = "Выберите часовой пояс:" if lang == "ru" else "Select your timezone:"
    await cq.message.edit_text(text, reply_markup=_kb_tz(page), parse_mode="HTML")
    await cq.answer()


# ─── Setup wizard — step 2: timezone chosen → finalize ───────────────────────

@router.callback_query(SetupFSM.timezone, F.data.startswith("setup_tz_"))
async def setup_tz(cq: CallbackQuery, state: FSMContext):
    tz = cq.data[len("setup_tz_"):]
    fsm_data = await state.get_data()
    lang = fsm_data.get("lang", "en")

    from api.database import async_session, Admin, AppSetting
    from api.routers.settings_router import _apply_setting_sync

    user = cq.from_user
    async with async_session() as session:
        # Register the first admin
        existing = await session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(Admin)
            .where(Admin.telegram_id == user.id)
        )
        if not existing.scalar_one_or_none():
            session.add(Admin(
                telegram_id=user.id,
                username=user.username,
                added_by=None,
            ))

        # Save lang and tz settings
        for key, value in [("bot_lang", lang), ("tz", tz)]:
            row = await session.get(AppSetting, key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))

        await session.commit()

    # Apply to runtime cache immediately
    _apply_setting_sync("bot_lang", lang)
    _apply_setting_sync("tz", tz)

    await state.clear()

    if lang == "ru":
        text = (
            f"✅ <b>Настройка завершена!</b>\n\n"
            f"  🌍 Часовой пояс: <code>{tz}</code>\n"
            f"  🌐 Язык: Русский\n\n"
            f"Вы зарегистрированы как первый администратор.\n"
            f"Добро пожаловать! 🎉"
        )
    else:
        text = (
            f"✅ <b>Setup complete!</b>\n\n"
            f"  🌍 Timezone: <code>{tz}</code>\n"
            f"  🌐 Language: English\n\n"
            f"You have been registered as the first administrator.\n"
            f"Welcome! 🎉"
        )

    await cq.message.edit_text(text, reply_markup=kb_main_menu(), parse_mode="HTML")
    await cq.answer()


# ─── Catch-all: show setup prompt if still in setup_mode ─────────────────────

@router.message(F.text, SetupFSM.language)
@router.message(F.text, SetupFSM.timezone)
async def setup_please_use_buttons(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    await msg.answer(
        "Пожалуйста, используйте кнопки." if lang == "ru" else "Please use the buttons above."
    )


# ─── Helper ───────────────────────────────────────────────────────────────────

def _get_lang() -> str:
    from api.routers.settings_router import get_runtime
    return get_runtime("bot_lang", "en")
