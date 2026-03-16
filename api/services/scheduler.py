"""
Background scheduler — runs inside the FastAPI lifespan as an asyncio task.

Checks every 5 minutes whether any periodic job is due:
  - auto-backup:        creates ZIP and sends to all Telegram admins
  - auto-log-cleanup:   truncates nginx access/error logs

Intervals are stored in AppSetting (key: backup_auto_hours / logs_clean_hours).
Last-run timestamps are stored in AppSetting (key: backup_last_at / logs_clean_last_at).

Values of 0 (or missing) mean "disabled".
"""
import asyncio
import logging
import time
from pathlib import Path

from api.services.backup_service import build_backup_zip

logger = logging.getLogger(__name__)

_CHECK_INTERVAL = 300   # check every 5 minutes
BASE_DIR = Path(__file__).parent.parent.parent


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_int_setting(key: str) -> int:
    """Read scheduler-specific setting directly from DB (bypasses _ALLOWED whitelist)."""
    from api.database import async_session, AppSetting
    try:
        async with async_session() as session:
            row = await session.get(AppSetting, key)
            return int(row.value) if row and row.value else 0
    except (ValueError, TypeError):
        return 0


async def _set_setting(key: str, value: str) -> None:
    """Write scheduler-specific setting directly to DB."""
    from api.database import async_session, AppSetting
    async with async_session() as session:
        row = await session.get(AppSetting, key)
        if row:
            row.value = value
        else:
            session.add(AppSetting(key=key, value=value))
        await session.commit()


async def _send_backup_to_admins(zip_bytes: bytes) -> None:
    """Send backup ZIP to all Telegram admin IDs via the running bot instance."""
    from api.services.bot_holder import get_bot

    bot = get_bot()
    if not bot:
        logger.warning("Scheduler: bot not available, skipping auto-backup send")
        return

    # Admin IDs come exclusively from the DB (no env fallback)
    admin_ids: set[int] = set()
    try:
        from api.database import async_session, Admin
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(select(Admin).where(Admin.is_active == True))
            for a in result.scalars().all():
                admin_ids.add(a.telegram_id)
    except Exception as e:
        logger.warning("Scheduler: could not load DB admins: %s", e)

    if not admin_ids:
        logger.warning("Scheduler: no admin IDs configured, backup not sent")
        return

    from aiogram.types import BufferedInputFile
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    file = BufferedInputFile(zip_bytes, filename=f"backup_{ts}.zip")

    for tg_id in admin_ids:
        try:
            await bot.send_document(tg_id, file, caption=f"💾 <b>Auto-backup</b> {ts}", parse_mode="HTML")
        except Exception as e:
            logger.warning("Scheduler: failed to send backup to %s: %s", tg_id, e)


def _truncate_logs() -> list[str]:
    """Truncate nginx access and error logs. Returns list of cleared filenames."""
    logs_dir = BASE_DIR / "nginx" / "logs"
    cleared = []
    for log_file in logs_dir.glob("*.log"):
        try:
            log_file.write_bytes(b"")
            cleared.append(log_file.name)
        except Exception as e:
            logger.warning("Scheduler: could not clear %s: %s", log_file, e)
    return cleared


# ─── Job implementations ──────────────────────────────────────────────────────

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
    """Truncate logs and record timestamp. Returns cleared file names."""
    logger.info("Scheduler: running auto log cleanup")
    cleared = _truncate_logs()
    await _set_setting("logs_clean_last_at", str(int(time.time())))
    logger.info("Scheduler: cleared logs: %s", cleared)
    return cleared


# ─── Main loop ────────────────────────────────────────────────────────────────

async def scheduler_loop() -> None:
    """Background asyncio task — runs for the lifetime of the application."""
    logger.info("Scheduler: started (check interval %ds)", _CHECK_INTERVAL)

    while True:
        try:
            await asyncio.sleep(_CHECK_INTERVAL)
            now = int(time.time())

            # ── Auto-backup ───────────────────────────────────────────────────
            backup_hours = await _get_int_setting("backup_auto_hours")
            if backup_hours > 0:
                last_backup = await _get_int_setting("backup_last_at")
                if now - last_backup >= backup_hours * 3600:
                    await run_backup_job()

            # ── Auto log cleanup ──────────────────────────────────────────────
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
