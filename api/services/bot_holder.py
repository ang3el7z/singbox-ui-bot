"""
Holds a reference to the running aiogram Bot instance so that
background scheduler tasks (auto-backup, alerts) can send messages.
"""
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot

_bot: Optional["Bot"] = None


def set_bot(bot: "Bot") -> None:
    global _bot
    _bot = bot


def get_bot() -> Optional["Bot"]:
    return _bot
