"""
App settings — stored in the AppSetting table (DB is the single source of truth).
Values are seeded from .env on first startup by api/main.py:_seed_and_apply_settings().

Supported keys:
  tz        — IANA timezone string (e.g. "Europe/Moscow", "UTC")
  bot_lang  — "ru" or "en"
"""
import os
import time as _time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.database import AppSetting, async_session
from api.deps import require_any_auth, audit

router = APIRouter()

# Keys that are allowed to be read/written via this API
_ALLOWED = {"tz", "bot_lang"}


# ─── Helpers (also imported by bot handlers) ──────────────────────────────────

async def get_setting(key: str, default: str = "") -> str:
    """Read a setting from the AppSetting table (seeded from .env on first startup)."""
    async with async_session() as session:
        row = await session.get(AppSetting, key)
        if row and row.value is not None:
            return row.value
    return default


async def set_setting(key: str, value: str) -> None:
    """Upsert a setting into AppSetting table and apply it to the running process."""
    if key not in _ALLOWED:
        raise ValueError(f"Setting '{key}' is not allowed")
    async with async_session() as session:
        row = await session.get(AppSetting, key)
        if row:
            row.value = value
        else:
            session.add(AppSetting(key=key, value=value))
        await session.commit()
    # Apply immediately to the running process
    _apply_setting(key, value)


def _apply_setting(key: str, value: str) -> None:
    """Apply setting changes to the current process without restart."""
    if key == "tz":
        os.environ["TZ"] = value
        try:
            _time.tzset()  # Linux/macOS only; no-op on Windows
        except AttributeError:
            pass  # Windows — timezone env var won't take effect until process restart
    # bot_lang is read from DB each time, no action needed here


async def get_all_settings() -> dict:
    """Return all current settings from DB (always seeded on startup)."""
    return {
        "tz":       await get_setting("tz"),
        "bot_lang": await get_setting("bot_lang"),
    }


# ─── API endpoints ────────────────────────────────────────────────────────────

class SettingUpdate(BaseModel):
    value: str


@router.get("/", summary="Get all runtime settings")
async def list_settings(auth=Depends(require_any_auth)):
    return await get_all_settings()


@router.get("/{key}", summary="Get a single setting")
async def get_one(key: str, auth=Depends(require_any_auth)):
    if key not in _ALLOWED:
        raise HTTPException(status_code=404, detail=f"Unknown setting '{key}'")
    value = await get_setting(key)
    return {"key": key, "value": value}


@router.post("/{key}", summary="Update a setting")
async def update_setting(key: str, body: SettingUpdate, auth=Depends(require_any_auth)):
    if key not in _ALLOWED:
        raise HTTPException(status_code=404, detail=f"Unknown setting '{key}'")

    value = body.value.strip()

    # Basic validation
    if key == "bot_lang" and value not in ("ru", "en"):
        raise HTTPException(status_code=400, detail="bot_lang must be 'ru' or 'en'")
    if key == "tz" and not value:
        raise HTTPException(status_code=400, detail="tz cannot be empty")

    await set_setting(key, value)
    await audit(auth["actor"], f"setting_update_{key}", f"value={value}")
    return {"key": key, "value": value, "applied": True}
