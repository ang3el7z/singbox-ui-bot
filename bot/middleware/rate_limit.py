import time
from typing import Any, Awaitable, Callable, Dict
from collections import defaultdict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, rate: int = 30, per: int = 60):
        """
        :param rate: max number of requests
        :param per: time window in seconds
        """
        self.rate = rate
        self.per = per
        self._requests: Dict[int, list] = defaultdict(list)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        user_id = user.id
        now = time.time()
        window_start = now - self.per
        self._requests[user_id] = [t for t in self._requests[user_id] if t > window_start]

        if len(self._requests[user_id]) >= self.rate:
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Too many requests, please wait.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⏳ Too many requests. Please wait a moment.")
            return

        self._requests[user_id].append(now)
        return await handler(event, data)
