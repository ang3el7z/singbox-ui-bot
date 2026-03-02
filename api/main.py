"""
FastAPI application — single source of truth for all business logic.
Both the Telegram bot and Web UI are thin clients of this API.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from api.config import settings
from api.database import init_db, async_session, WebUser
from api.deps import hash_password
from api.routers import auth, server, clients, inbounds, routing, adguard, nginx, federation, admin
from api.routers import docs_router, settings_router
from api.routers import maintenance as maintenance_router
from sqlalchemy import select


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    await init_db()
    await _ensure_default_web_user()
    await _seed_and_apply_settings()
    # Start background scheduler
    from api.services.scheduler import scheduler_loop
    _sched_task = asyncio.create_task(scheduler_loop())
    yield
    _sched_task.cancel()
    try:
        await _sched_task
    except asyncio.CancelledError:
        pass


async def _seed_and_apply_settings() -> None:
    """
    Runtime settings (domain, tz, bot_lang) live ONLY in the AppSetting table.
    They are collected via the bot setup wizard on first /start — never from .env.
    On every startup we re-apply whatever is in the DB to the running process.
    """
    from api.database import AppSetting, async_session
    from api.routers.settings_router import _apply_setting_sync

    async with async_session() as session:
        for key in ("tz", "bot_lang", "domain"):
            row = await session.get(AppSetting, key)
            if row and row.value:
                _apply_setting_sync(key, row.value)


async def _ensure_default_web_user() -> None:
    """Create default web admin if no web users exist."""
    async with async_session() as session:
        result = await session.execute(select(WebUser))
        if result.scalar_one_or_none() is None:
            user = WebUser(
                username=settings.web_admin_user,
                password_hash=hash_password(settings.web_admin_password),
            )
            session.add(user)
            await session.commit()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Singbox UI Bot API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/api/swagger",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routers
    app.include_router(auth.router,       prefix="/api/auth",       tags=["auth"])
    app.include_router(server.router,     prefix="/api/server",     tags=["server"])
    app.include_router(clients.router,    prefix="/api/clients",    tags=["clients"])
    app.include_router(inbounds.router,   prefix="/api/inbounds",   tags=["inbounds"])
    app.include_router(routing.router,    prefix="/api/routing",    tags=["routing"])
    app.include_router(adguard.router,    prefix="/api/adguard",    tags=["adguard"])
    app.include_router(nginx.router,      prefix="/api/nginx",      tags=["nginx"])
    app.include_router(federation.router, prefix="/api/federation", tags=["federation"])
    app.include_router(admin.router,      prefix="/api/admin",      tags=["admin"])
    app.include_router(docs_router.router,        prefix="/api/docs",        tags=["docs"])
    app.include_router(settings_router.router,   prefix="/api/settings",   tags=["settings"])
    app.include_router(maintenance_router.router, prefix="/api/maintenance", tags=["maintenance"])

    # Federation HMAC endpoint (public, no JWT — authenticated via HMAC)
    from api.services.federation_service import fed_router
    app.include_router(fed_router)

    # Serve web UI static files
    web_dir = Path(__file__).parent.parent / "web"
    if web_dir.exists():
        app.mount("/web", StaticFiles(directory=str(web_dir), html=True), name="web")

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "2.0.0"}

    return app


app = create_app()
