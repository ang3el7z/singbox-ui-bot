from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy import select, func

from api.database import async_session, Admin
from api.routers.settings_router import get_runtime


class AdminAuthMiddleware(BaseMiddleware):
    """
    Access control for all bot updates.

    - No admins in DB yet  → setup_mode=True, let the update through.
      The setup wizard in start.py will register the first user as admin.
    - Admins exist, user is admin → setup_mode=False, let through.
    - Admins exist, user is NOT admin → deny and return.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return

        admin_count = await self._count_admins()

        if admin_count == 0:
            # First run — no admins yet; let anyone through the setup wizard
            data["setup_mode"] = True
            return await handler(event, data)

        is_admin = await self._is_admin(user.id)

        if not is_admin:
            lang = get_runtime("bot_lang")
            if isinstance(event, Message):
                await event.answer(
                    "⛔ Доступ запрещён. Вы не являетесь администратором."
                    if lang == "ru"
                    else "⛔ Access denied. You are not an administrator."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "⛔ Нет доступа" if lang == "ru" else "⛔ No access",
                    show_alert=True,
                )
            return

        data["setup_mode"] = False
        return await handler(event, data)

    async def _count_admins(self) -> int:
        async with async_session() as session:
            result = await session.execute(
                select(func.count()).select_from(Admin).where(Admin.is_active == True)
            )
            return result.scalar() or 0

    async def _is_admin(self, user_id: int) -> bool:
        async with async_session() as session:
            result = await session.execute(
                select(Admin).where(Admin.telegram_id == user_id, Admin.is_active == True)
            )
            return result.scalar_one_or_none() is not None
