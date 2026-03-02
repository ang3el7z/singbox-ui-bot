from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from bot.keyboards.main import main_menu_kb
from bot.texts import t

router = Router()


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message) -> None:
    await message.answer(t("welcome"), reply_markup=main_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(t("main_menu"), reply_markup=main_menu_kb(), parse_mode="HTML")
    await callback.answer()
