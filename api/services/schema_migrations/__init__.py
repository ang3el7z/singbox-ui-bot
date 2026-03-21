"""
Schema migrations package.

Public API:
- run_migrations()
- CURRENT_SCHEMA_VERSION
"""
from .core import CURRENT_SCHEMA_VERSION, run_migrations

__all__ = ["CURRENT_SCHEMA_VERSION", "run_migrations"]
