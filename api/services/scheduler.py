"""
Background scheduler running inside FastAPI lifespan.

Checks every 5 minutes whether periodic jobs are due:
- auto-backup: creates ZIP and sends to Telegram admins
- auto-log-cleanup: truncates nginx access/error logs
- update-cache refresh: refreshes cached update info for bot/web

Intervals are stored in AppSetting:
- backup_auto_hours
- logs_clean_hours

Last-run timestamps:
- backup_last_at
- logs_clean_last_at

Value 0 (or missing) means disabled.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from api.services import update_service
from api.services.backup_service import build_backup_zip

logger = logging.getLogger(__name__)

_CHECK_INTERVAL = 300  # 5 minutes
BASE_DIR = Path(__file__).parent.parent.parent


async def _get_int_setting(key: str) -> int:
    """Read scheduler-specific setting directly from DB."""
    from api.database import AppSetting, async_session

    try:
        async with async_session() as session:
            row = await session.get(AppSetting, key)
            return int(row.value) if row and row.value else 0
    except (ValueError, TypeError):
        return 0


async def _set_setting(key: str, value: str) -> None:
    """Write scheduler-specific setting directly to DB."""
    from api.database import AppSetting, async_session

    async with async_session() as session:
        row = await session.get(AppSetting, key)
        if row:
            row.value = value
        else:
            session.add(AppSetting(key=key, value=value))
        await session.commit()


async def _send_backup_to_admins(zip_bytes: bytes) -> None:
    """Send backup ZIP to all Telegram admin IDs via running bot instance."""
    from api.services.bot_holder import get_bot

    bot = get_bot()
    if not bot:
        logger.warning("Scheduler: bot not available, skipping auto-backup send")
        return

    admin_ids: set[int] = set()
    try:
        from sqlalchemy import select
        from api.database import Admin, async_session

        async with async_session() as session:
            result = await session.execute(select(Admin).where(Admin.is_active == True))
            for admin in result.scalars().all():
                admin_ids.add(admin.telegram_id)
    except Exception as e:
        logger.warning("Scheduler: could not load DB admins: %s", e)

    if not admin_ids:
        logger.warning("Scheduler: no admin IDs configured, backup not sent")
        return

    from datetime import datetime
    from aiogram.types import BufferedInputFile

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    file = BufferedInputFile(zip_bytes, filename=f"backup_{ts}.zip")

    for tg_id in admin_ids:
        try:
            await bot.send_document(tg_id, file, caption=f"<b>Auto-backup</b> {ts}", parse_mode="HTML")
        except Exception as e:
            logger.warning("Scheduler: failed to send backup to %s: %s", tg_id, e)


def _truncate_logs() -> list[str]:
    """Truncate nginx access/error logs and return cleared filenames."""
    logs_dir = BASE_DIR / "nginx" / "logs"
    cleared: list[str] = []
    for log_file in logs_dir.glob("*.log"):
        try:
            log_file.write_bytes(b"")
            cleared.append(log_file.name)
        except Exception as e:
            logger.warning("Scheduler: could not clear %s: %s", log_file, e)
    return cleared


async def run_backup_job() -> bool:
    """Create backup and send to admins. Returns True on success."""
    logger.info("Scheduler: running auto-backup")
    try:
        zip_bytes = build_backup_zip()
        await _send_backup_to_admins(zip_bytes)
        await _set_setting("backup_last_at", str(int(time.time())))
        logger.info("Scheduler: auto-backup sent (%d bytes)", len(zip_bytes))
        return True
    except Exception as e:
        logger.error("Scheduler: auto-backup failed: %s", e)
        return False


async def run_log_cleanup_job() -> list[str]:
    """Truncate logs and record timestamp. Returns cleared filenames."""
    logger.info("Scheduler: running auto log cleanup")
    cleared = _truncate_logs()
    await _set_setting("logs_clean_last_at", str(int(time.time())))
    logger.info("Scheduler: cleared logs: %s", cleared)
    return cleared


async def run_update_cache_refresh_job() -> bool:
    """Refresh cached update info (with remote fetch) for bot/web consumers."""
    try:
        data = await asyncio.to_thread(update_service.refresh_update_info_cache, True)
        logger.info(
            "Scheduler: update cache refreshed (current=%s, latest=%s)",
            data.get("current_version", "-"),
            data.get("latest_tag", "-"),
        )
        return True
    except Exception as e:
        logger.warning("Scheduler: update cache refresh failed: %s", e)
        return False


async def scheduler_loop() -> None:
    """Background asyncio task running for the full app lifetime."""
    logger.info("Scheduler: started (check interval %ds)", _CHECK_INTERVAL)
    await run_update_cache_refresh_job()

    while True:
        try:
            await asyncio.sleep(_CHECK_INTERVAL)
            now = int(time.time())

            # Keep update cache fresh for all consumers.
            await run_update_cache_refresh_job()

            backup_hours = await _get_int_setting("backup_auto_hours")
            if backup_hours > 0:
                last_backup = await _get_int_setting("backup_last_at")
                if now - last_backup >= backup_hours * 3600:
                    await run_backup_job()

            clean_hours = await _get_int_setting("logs_clean_hours")
            if clean_hours > 0:
                last_clean = await _get_int_setting("logs_clean_last_at")
                if now - last_clean >= clean_hours * 3600:
                    await run_log_cleanup_job()

        except asyncio.CancelledError:
            logger.info("Scheduler: stopped")
            break
        except Exception as e:
            logger.error("Scheduler: unexpected error: %s", e)
