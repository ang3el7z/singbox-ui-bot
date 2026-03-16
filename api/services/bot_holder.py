"""
Holds a reference to the running aiogram Bot instance so that
background scheduler tasks (auto-backup, alerts) can send messages.
"""
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher

_bot: Optional["Bot"] = None
_dispatcher: Optional["Dispatcher"] = None


def set_bot(bot: "Bot") -> None:
    global _bot
    _bot = bot


def get_bot() -> Optional["Bot"]:
    return _bot


def set_dispatcher(dispatcher: "Dispatcher") -> None:
    global _dispatcher
    _dispatcher = dispatcher


def get_dispatcher() -> Optional["Dispatcher"]:
    return _dispatcher
