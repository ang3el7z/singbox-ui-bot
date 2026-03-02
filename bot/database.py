# Backward-compat shim — all DB models now live in api/database.py
from api.database import (
    Base, engine, async_session, get_db, init_db,
    WebUser, Admin, Client, Inbound, AuditLog, FederationNode, AppSetting,
)

__all__ = [
    "Base", "engine", "async_session", "get_db", "init_db",
    "WebUser", "Admin", "Client", "Inbound", "AuditLog", "FederationNode", "AppSetting",
]
