"""
Migration versions auto-discovery.

Each migration file must be named like:
  vNNN_<name>.py
and expose:
  - MIGRATION_VERSION: int
  - MIGRATION_NAME: str
  - run_migration: async callable without args
"""
from __future__ import annotations

import inspect
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from typing import Awaitable, Callable

MigrationSpec = tuple[int, str, Callable[[], Awaitable[None]]]


def _load_specs() -> list[MigrationSpec]:
    specs: list[MigrationSpec] = []
    pkg_dir = Path(__file__).resolve().parent
    prefix = __name__ + "."

    for module_info in sorted(iter_modules([str(pkg_dir)]), key=lambda item: item.name):
        name = module_info.name
        if not name.startswith("v") or name == "__init__":
            continue

        mod = import_module(prefix + name)
        version = getattr(mod, "MIGRATION_VERSION", None)
        title = getattr(mod, "MIGRATION_NAME", None)
        fn = getattr(mod, "run_migration", None)

        if not isinstance(version, int) or version <= 0:
            raise RuntimeError(f"{name}: MIGRATION_VERSION must be positive int")
        if not isinstance(title, str) or not title.strip():
            raise RuntimeError(f"{name}: MIGRATION_NAME must be non-empty string")
        if fn is None or not callable(fn) or not inspect.iscoroutinefunction(fn):
            raise RuntimeError(f"{name}: run_migration must be async callable")

        specs.append((version, title.strip(), fn))

    versions = [v for v, _, _ in specs]
    if len(set(versions)) != len(versions):
        raise RuntimeError("Duplicate migration versions detected")

    return sorted(specs, key=lambda item: item[0])


MIGRATION_SPECS: list[MigrationSpec] = _load_specs()
