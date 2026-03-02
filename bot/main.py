"""
Singbox UI Bot — entry point.
Starts FastAPI (all business logic) + aiogram bot in the same process.
Bot handlers are thin clients calling FastAPI via X-Internal-Token.
"""
import asyncio
import logging
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from api.config import settings
from api.main import app as fastapi_app

from bot.middleware.auth import AdminAuthMiddleware
from bot.middleware.rate_limit import RateLimitMiddleware
from bot.handlers import start, server, clients, inbounds, routing, adguard, nginx, federation, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.update.middleware(AdminAuthMiddleware())
    dp.update.middleware(RateLimitMiddleware(rate=30, per=60))

    dp.include_router(start.router)
    dp.include_router(server.router)
    dp.include_router(clients.router)
    dp.include_router(inbounds.router)
    dp.include_router(routing.router)
    dp.include_router(adguard.router)
    dp.include_router(nginx.router)
    dp.include_router(federation.router)
    dp.include_router(admin.router)

    return dp


async def run_bot(bot: Bot, dp: Dispatcher) -> None:
    if settings.use_webhook:
        logger.info("Starting webhook mode: %s", settings.webhook_url)
        await bot.set_webhook(settings.webhook_url)
    else:
        logger.info("Starting polling mode")
        await dp.start_polling(bot)


async def run_api() -> None:
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=settings.webhook_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    bot = create_bot()
    dp = create_dispatcher()

    await asyncio.gather(
        run_api(),
        run_bot(bot, dp),
    )


if __name__ == "__main__":
    asyncio.run(main())
