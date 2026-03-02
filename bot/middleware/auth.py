from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.config import settings
from bot.database import async_session, Admin, AuditLog


class AdminAuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return

        user_id = user.id
        is_admin = await self._is_admin(user_id)

        if not is_admin:
            if isinstance(event, Message):
                await event.answer(
                    "⛔ Доступ запрещён. Вы не являетесь администратором." if settings.bot_lang == "ru"
                    else "⛔ Access denied. You are not an administrator."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "⛔ Нет доступа" if settings.bot_lang == "ru" else "⛔ No access",
                    show_alert=True,
                )
            return

        data["is_admin"] = True
        return await handler(event, data)

    async def _is_admin(self, user_id: int) -> bool:
        # First check static env list
        if user_id in settings.admin_ids_list:
            return True
        # Then check DB
        async with async_session() as session:
            result = await session.execute(
                select(Admin).where(Admin.telegram_id == user_id, Admin.is_active == True)
            )
            return result.scalar_one_or_none() is not None


async def log_action(user_id: int, action: str, details: str = None) -> None:
    async with async_session() as session:
        log = AuditLog(telegram_id=user_id, action=action, details=details)
        session.add(log)
        await session.commit()
