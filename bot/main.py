"""
Singbox UI Bot — main entry point.
Runs aiogram bot (polling or webhook) alongside FastAPI (federation API).
"""
import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.config import settings
from bot.database import init_db
from bot.middleware.auth import AdminAuthMiddleware
from bot.middleware.rate_limit import RateLimitMiddleware

# Import all routers
from bot.handlers import start, server, clients, inbounds, routing, adguard, nginx, federation, admin
from bot.services.federation_service import fed_router


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


def create_app(bot: Bot, dp: Dispatcher) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db()
        logger.info("Database initialised")
        if settings.use_webhook:
            await bot.set_webhook(settings.webhook_url)
            logger.info(f"Webhook set: {settings.webhook_url}")
        else:
            await bot.delete_webhook(drop_pending_updates=True)
        yield
        await bot.session.close()
        logger.info("Bot session closed")

    app = FastAPI(title="Singbox UI Bot", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(fed_router)

    if settings.use_webhook:
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=settings.webhook_path)

    @app.get("/health")
    async def health():
        return {"status": "ok", "domain": settings.domain}

    return app


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Starting bot in polling mode")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def run_webhook(bot: Bot, dp: Dispatcher) -> None:
    app = create_app(bot, dp)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.webhook_port,
        log_level="info",
    )
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


async def main() -> None:
    bot = create_bot()
    dp = create_dispatcher()
    if settings.use_webhook:
        logger.info(f"Starting webhook server on port {settings.webhook_port}")
        await run_webhook(bot, dp)
    else:
        await run_polling(bot, dp)


if __name__ == "__main__":
    asyncio.run(main())
