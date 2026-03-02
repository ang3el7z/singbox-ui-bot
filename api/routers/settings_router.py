"""
Runtime settings — stored exclusively in the AppSetting table (DB is the single
source of truth).  Values are written here by the bot setup wizard on first /start.
.env does NOT contain these values (domain, tz, bot_lang).

Supported keys:
  tz        — IANA timezone string (e.g. "Europe/Moscow", "UTC")
  bot_lang  — "ru" or "en"
  domain    — server domain (e.g. "example.com") — changing triggers nginx reload
  ssh_port  — SSH port for UFW (1–65535); apply on host with: singbox-ui-bot firewall
"""
import os
import re
import time as _time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.database import AppSetting, async_session
from api.deps import require_any_auth, audit

router = APIRouter()

# Keys that are allowed to be read/written via this API
_ALLOWED = {"tz", "bot_lang", "domain", "ssh_port"}

_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$")

# ─── In-memory runtime cache ──────────────────────────────────────────────────
# Updated by _apply_setting_sync on every startup + on every save.
# Sync code (nginx_service, federation_service, etc.) reads from here — no DB
# query needed, no asyncio required.
_runtime: dict[str, str] = {
    "tz":       "UTC",
    "bot_lang": "ru",
    "domain":   "",
    "ssh_port": "22",
}


def get_runtime(key: str, default: str = "") -> str:
    """Synchronous read of a runtime setting from the in-memory cache."""
    return _runtime.get(key, default)


# ─── Helpers (also imported by bot handlers and main.py) ──────────────────────

async def get_setting(key: str, default: str = "") -> str:
    """Read a setting from the AppSetting table."""
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
    await _apply_setting(key, value)


def _apply_setting_sync(key: str, value: str) -> None:
    """Update in-memory cache and apply side effects (env vars). Called at startup."""
    _runtime[key] = value
    if key == "ssh_port":
        _write_ssh_port_file(value)
    if key == "tz":
        os.environ["TZ"] = value
        try:
            _time.tzset()
        except AttributeError:
            pass


def _write_ssh_port_file(port: str) -> None:
    """Write ssh_port to host_data so manage.sh firewall can read it."""
    try:
        host_data = __import__("pathlib").Path("/app/host_data")
        if host_data.is_dir():
            (host_data / "ssh_port").write_text(port.strip() + "\n")
    except Exception:
        pass


async def _apply_setting(key: str, value: str) -> None:
    """Apply setting change immediately: env vars + side effects (nginx reload)."""
    _apply_setting_sync(key, value)
    if key == "domain":
        # Regenerate nginx config and reload — domain affects server_name, SSL paths, etc.
        try:
            from api.services import nginx_service
            config_text = nginx_service.generate_config(domain=value)
            nginx_service.write_config(config_text)
            await nginx_service.reload_nginx()
        except Exception as e:
            # Log but don't fail — admin can reload manually
            import logging
            logging.getLogger(__name__).warning("nginx reload after domain change failed: %s", e)
    elif key == "ssh_port":
        _write_ssh_port_file(value)


async def get_all_settings() -> dict:
    """Return all current settings from DB (always seeded on startup)."""
    return {
        "tz":       await get_setting("tz"),
        "bot_lang": await get_setting("bot_lang"),
        "domain":   await get_setting("domain"),
        "ssh_port": await get_setting("ssh_port") or "22",
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

    # Validation
    if key == "bot_lang" and value not in ("ru", "en"):
        raise HTTPException(status_code=400, detail="bot_lang must be 'ru' or 'en'")
    if key == "tz" and not value:
        raise HTTPException(status_code=400, detail="tz cannot be empty")
    if key == "domain":
        if not _DOMAIN_RE.match(value):
            raise HTTPException(status_code=400, detail="Invalid domain format (e.g. example.com)")
    if key == "ssh_port":
        try:
            p = int(value)
            if p < 1 or p > 65535:
                raise ValueError("out of range")
        except ValueError:
            raise HTTPException(status_code=400, detail="ssh_port must be 1–65535")

    await set_setting(key, value)
    await audit(auth["actor"], f"setting_update_{key}", f"value={value}")

    extra = {}
    if key == "domain":
        extra["note"] = "Nginx config regenerated. Re-issue SSL if domain changed."

    return {"key": key, "value": value, "applied": True, **extra}
