# Backward-compat shim — all config now lives in api/config.py
from api.config import settings, Settings

__all__ = ["settings", "Settings"]
