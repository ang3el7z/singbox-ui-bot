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
from aiogram.types import BotCommand

from api.config import settings
from api.main import app as fastapi_app

from bot.middleware.auth import AdminAuthMiddleware
from bot.middleware.rate_limit import RateLimitMiddleware
from bot.handlers import start, server, clients, inbounds, routing, adguard, nginx, federation, admin, docs, settings as settings_handlers, maintenance, client_templates

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
    dp.include_router(docs.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(maintenance.router)
    dp.include_router(client_templates.router)

    return dp


async def setup_bot_commands(bot: Bot) -> None:
    default_commands = [
        BotCommand(command="menu", description="Quick menu"),
    ]
    ru_commands = [
        BotCommand(command="menu", description="Быстрое меню"),
    ]
    try:
        await bot.set_my_commands(default_commands)
        await bot.set_my_commands(ru_commands, language_code="ru")
    except Exception as exc:
        logger.warning("Failed to set bot commands: %s", exc)


async def run_bot(bot: Bot, dp: Dispatcher) -> None:
    await setup_bot_commands(bot)
    if settings.use_webhook:
        logger.info("Starting webhook mode: %s", settings.webhook_url)
        kwargs = {}
        if settings.webhook_secret:
            kwargs["secret_token"] = settings.webhook_secret
        await bot.set_webhook(settings.webhook_url, **kwargs)
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

    # Register bot reference so scheduler can send messages to admins
    from api.services.bot_holder import set_bot, set_dispatcher
    set_bot(bot)
    set_dispatcher(dp)

    await asyncio.gather(
        run_api(),
        run_bot(bot, dp),
    )


if __name__ == "__main__":
    asyncio.run(main())
