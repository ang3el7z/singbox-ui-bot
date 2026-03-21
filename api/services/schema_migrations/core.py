"""
Application data migrations core.

Goals:
- Keep runtime code single-path (no permanent dual logic).
- Keep persisted schema changes explicit and versioned.
- Track applied migration level via AppSetting(schema_version).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from api.database import AppSetting, async_session
from api.services.schema_migrations.versions import MIGRATION_SPECS

logger = logging.getLogger(__name__)

SCHEMA_VERSION_KEY = "schema_version"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    fn: Callable[[], Awaitable[None]]


MIGRATIONS: list[Migration] = [
    Migration(version=version, name=name, fn=fn)
    for version, name, fn in MIGRATION_SPECS
]
CURRENT_SCHEMA_VERSION = max((m.version for m in MIGRATIONS), default=0)


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
