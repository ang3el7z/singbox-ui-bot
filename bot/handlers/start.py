from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from bot.keyboards.main import kb_main_menu

router = Router()


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(msg: Message):
    await msg.answer(
        "👋 <b>Singbox UI Bot</b>\n\nChoose a section:",
        reply_markup=kb_main_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cq: CallbackQuery):
    await cq.message.edit_text(
        "👋 <b>Singbox UI Bot</b>\n\nChoose a section:",
        reply_markup=kb_main_menu(),
        parse_mode="HTML",
    )
