from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.sui_api import sui, SuiAPIError
from bot.keyboards.main import back_kb
from bot.texts import t
from bot.utils import format_bytes, format_uptime, truncate
from bot.middleware.auth import log_action

router = Router()

PAGE_SIZE = 50


def server_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("server_status"), callback_data="server:status"),
        InlineKeyboardButton(text=t("server_logs"), callback_data="server:logs:0"),
    )
    builder.row(
        InlineKeyboardButton(text=t("server_restart"), callback_data="server:restart"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:server")
async def cb_server_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(t("server_menu"), reply_markup=server_menu_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "server:status")
async def cb_server_status(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        status = await sui.get_status(full=True)
        onlines = await sui.get_onlines()

        running = status.get("running", False)
        uptime_sec = status.get("uptime", 0)
        dl = status.get("netIO", {}).get("down", 0)
        ul = status.get("netIO", {}).get("up", 0)
        online_count = len(onlines) if isinstance(onlines, list) else 0

        text = t(
            "server_status_tpl",
            status="🟢 работает" if running else "🔴 остановлен",
            uptime=format_uptime(uptime_sec),
            dl=format_bytes(dl),
            ul=format_bytes(ul),
            online=online_count,
        )
    except SuiAPIError as e:
        text = t("error", msg=str(e))

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("refresh"), callback_data="server:status"),
        InlineKeyboardButton(text=t("back"), callback_data="menu:server"),
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "server:restart")
async def cb_server_restart(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(t("server_restarting"), parse_mode="HTML")
    try:
        await sui.restart_singbox()
        await log_action(callback.from_user.id, "restart_singbox")
        text = t("server_restarted")
    except SuiAPIError as e:
        text = t("error", msg=str(e))
    await callback.message.edit_text(text, reply_markup=back_kb("menu:server"), parse_mode="HTML")


@router.callback_query(F.data.startswith("server:logs:"))
async def cb_server_logs(callback: CallbackQuery) -> None:
    await callback.answer()
    offset = int(callback.data.split(":")[2])
    try:
        logs = await sui.get_logs(count=PAGE_SIZE)
        if not logs:
            text = "📜 Логи пустые."
        else:
            lines = logs[-(PAGE_SIZE):]
            text = "📜 <b>Логи Sing-Box</b>\n\n<code>" + truncate("\n".join(str(l) for l in lines), 3500) + "</code>"
    except SuiAPIError as e:
        text = t("error", msg=str(e))

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("refresh"), callback_data=f"server:logs:{offset}"),
        InlineKeyboardButton(text=t("back"), callback_data="menu:server"),
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
