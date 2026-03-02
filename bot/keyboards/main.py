from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.texts import t


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🖥 " + ("Сервер" if True else "Server"), callback_data="menu:server"),
        InlineKeyboardButton(text="👥 " + ("Клиенты" if True else "Clients"), callback_data="menu:clients"),
    )
    builder.row(
        InlineKeyboardButton(text="📡 Inbounds", callback_data="menu:inbounds"),
        InlineKeyboardButton(text="🔀 " + ("Маршрутизация" if True else "Routing"), callback_data="menu:routing"),
    )
    builder.row(
        InlineKeyboardButton(text="🛡 AdGuard", callback_data="menu:adguard"),
        InlineKeyboardButton(text="🌐 Nginx", callback_data="menu:nginx"),
    )
    builder.row(
        InlineKeyboardButton(text="🔗 " + ("Федерация" if True else "Federation"), callback_data="menu:federation"),
        InlineKeyboardButton(text="⚙️ " + ("Настройки" if True else "Settings"), callback_data="menu:admin"),
    )
    return builder.as_markup()


def back_kb(callback: str = "menu:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("back"), callback_data=callback)
    ]])


def confirm_delete_kb(confirm_cb: str, cancel_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("delete"), callback_data=confirm_cb),
        InlineKeyboardButton(text=t("cancel"), callback_data=cancel_cb),
    ]])


def paginate_kb(
    items: list,
    page: int,
    total_pages: int,
    callback_prefix: str,
    back_cb: str = "menu:main",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(InlineKeyboardButton(
            text=item["label"],
            callback_data=item["callback_data"],
        ))
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text=t("prev"), callback_data=f"{callback_prefix}:page:{page-1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text=t("next"), callback_data=f"{callback_prefix}:page:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text=t("back"), callback_data=back_cb))
    return builder.as_markup()
