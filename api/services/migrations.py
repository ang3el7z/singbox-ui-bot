"""
Application data migrations.

Goals:
- Keep runtime code single-path (no permanent dual logic).
- Apply compatibility only as one-time migrations.
- Track applied migration level via AppSetting(schema_version).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from api.database import AppSetting, async_session

logger = logging.getLogger(__name__)

SCHEMA_VERSION_KEY = "schema_version"
CURRENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    fn: Callable[[], Awaitable[None]]


async def _migration_001_web_ui_marker() -> None:
    """
    One-time marker rename:
      nginx/.site_enabled -> nginx/.web_ui_enabled

    Applies only once on upgrade. New installs simply mark schema version.
    """
    nginx_dir = Path(__file__).resolve().parents[2] / "nginx"
    old_marker = nginx_dir / ".site_enabled"
    new_marker = nginx_dir / ".web_ui_enabled"

    if old_marker.exists():
        new_marker.parent.mkdir(parents=True, exist_ok=True)
        new_marker.touch(exist_ok=True)
        old_marker.unlink(missing_ok=True)
        logger.info("migration[1]: moved %s -> %s", old_marker, new_marker)


MIGRATIONS: list[Migration] = [
    Migration(
        version=1,
        name="Move nginx site marker to web_ui marker",
        fn=_migration_001_web_ui_marker,
    ),
]


async def _get_schema_version() -> int:
    async with async_session() as session:
        row = await session.get(AppSetting, SCHEMA_VERSION_KEY)
        raw = (row.value or "").strip() if row else ""
        if not raw:
            return 0
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid schema_version value %r, assuming 0", raw)
            return 0


async def _set_schema_version(version: int) -> None:
    async with async_session() as session:
        row = await session.get(AppSetting, SCHEMA_VERSION_KEY)
        if row:
            row.value = str(version)
        else:
            session.add(AppSetting(key=SCHEMA_VERSION_KEY, value=str(version)))
        await session.commit()


async def run_migrations() -> int:
    """
    Run pending migrations in ascending order.
    Returns resulting schema version.
    """
    current = await _get_schema_version()
    if current > CURRENT_SCHEMA_VERSION:
        logger.warning(
            "DB schema_version=%s is newer than app supported=%s",
            current,
            CURRENT_SCHEMA_VERSION,
        )
        return current

    pending = [m for m in MIGRATIONS if m.version > current]
    if not pending:
        return current

    for migration in sorted(pending, key=lambda m: m.version):
        logger.info("Applying migration[%s]: %s", migration.version, migration.name)
        await migration.fn()
        await _set_schema_version(migration.version)
        current = migration.version

    return current

