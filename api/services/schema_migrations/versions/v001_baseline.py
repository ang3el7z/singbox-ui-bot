"""
Migration 001: baseline schema marker.

Keeps schema_version progression explicit without runtime compatibility logic.
"""

MIGRATION_VERSION = 1
MIGRATION_NAME = "Schema baseline"


async def run_migration() -> None:
    # Intentional no-op baseline migration.
    return None
