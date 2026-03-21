# Migrations Policy

## 1) Base mechanism: `schema_version + migrations`

- Source of truth: `app_settings.schema_version` (key in `AppSetting` table).
- Code location:
  - Core: `api/services/schema_migrations/core.py`
  - Versions: `api/services/schema_migrations/versions/`
  - Discovery: automatic by filename pattern `vNNN_*.py` (no manual registry).
- Startup flow:
  1. `init_db()` creates tables if needed.
  2. `run_migrations()` reads current `schema_version`.
  3. Pending migrations are applied in ascending order.
  4. After each successful migration, `schema_version` is updated.

Runtime code must stay single-path. Permanent dual logic is not allowed.

## 2) What we migrate

- Keep migrations for data/schema changes that affect persisted state.
- Keep backup/restore format stable and versioned.
- Do not add permanent compatibility branches in runtime code.

## 3) Developer checklist

1. Define the canonical target state.
2. Add a new file `api/services/schema_migrations/versions/vNNN_<name>.py`.
3. Export:
   - `MIGRATION_VERSION = NNN`
   - `MIGRATION_NAME = "Human-readable name"`
   - `async def run_migration() -> None`
4. Make migration idempotent (safe to re-run).
5. Keep runtime code working only with canonical state.
6. Document migration intent in PR/commit message.
