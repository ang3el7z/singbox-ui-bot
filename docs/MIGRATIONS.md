# Migrations Policy

## 1) Base mechanism: `schema_version + migrations`

- Source of truth: `app_settings.schema_version` (key in `AppSetting` table).
- Code location: `api/services/migrations.py`.
- Startup flow:
  1. `init_db()` creates tables if needed.
  2. `run_migrations()` reads current `schema_version`.
  3. Pending migrations are applied in ascending order.
  4. After each successful migration, `schema_version` is updated.
- Runtime code must stay single-path. Permanent dual logic is not allowed.

## 2) One-time migrator pattern

Use one-time migrators to convert old state to new state and then remove compatibility code.

Example pattern:

1. Add `Migration(version=N, name=..., fn=...)` to `MIGRATIONS`.
2. In `fn`, detect old format/state.
3. Convert old state to new state.
4. If old state is absent, do nothing (idempotent behavior).
5. Do not keep fallback reads in runtime logic.

Current example:

- Migration `1`: rename nginx marker
  - from `nginx/.site_enabled`
  - to `nginx/.web_ui_enabled`

## 3) Compatibility rules (short)

Keep compatibility only when at least one condition is true:

- We cannot safely auto-migrate in one step.
- External integrations depend on old format and cannot be switched immediately.
- Rollout requires phased migration between versions.

Remove compatibility when:

- One-time migrator exists and was shipped.
- Runtime can work with a single canonical format.
- At least one stable release has passed after migration (or project policy window is closed).

Hard rule:

- No hidden forever-compatibility. Every temporary compatibility path must have a removal issue/task and target release.

## 4) Developer checklist for new changes

1. Define new canonical format/state.
2. Implement one-time migration for existing installs.
3. Bump `CURRENT_SCHEMA_VERSION`.
4. Keep runtime logic only for canonical format.
5. Document migration intent in PR/commit message.
