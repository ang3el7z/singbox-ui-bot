"""
HTTP client from Telegram bot → FastAPI backend.
Authenticates with X-Internal-Token (shared secret, no JWT needed).
All bot handlers use this instead of calling services directly.
"""
import os
import httpx
from typing import Any, Optional

from api.config import settings

# When bot and API run in the same process (same container), localhost is correct.
# Override with API_BASE_URL env var if you ever split them into separate containers.
_BASE = os.getenv("API_BASE_URL", "http://localhost:8080")
_HEADERS = {"X-Internal-Token": settings.internal_token}


class APIError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"API {status}: {detail}")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=_BASE, headers=_HEADERS, timeout=30.0)


async def get(path: str, **params) -> Any:
    async with _client() as c:
        r = await c.get(path, params=params)
        if not r.is_success:
            raise APIError(r.status_code, _extract_detail(r))
        return r.json()


async def get_text(path: str, **params) -> str:
    """GET request that returns raw text (for plain-text responses like markdown)."""
    async with _client() as c:
        r = await c.get(path, params=params)
        if not r.is_success:
            raise APIError(r.status_code, _extract_detail(r))
        return r.text


# Convenience alias used by docs handler
async def api_get(path: str, raw_text: bool = False, **params) -> Any:
    if raw_text:
        return await get_text(path, **params)
    return await get(path, **params)


async def post(path: str, json: Any = None, **params) -> Any:
    async with _client() as c:
        r = await c.post(path, json=json, params=params)
        if not r.is_success:
            raise APIError(r.status_code, _extract_detail(r))
        return r.json()


async def patch(path: str, json: Any = None) -> Any:
    async with _client() as c:
        r = await c.patch(path, json=json)
        if not r.is_success:
            raise APIError(r.status_code, _extract_detail(r))
        return r.json()


async def delete(path: str, **params) -> Any:
    async with _client() as c:
        r = await c.delete(path, params=params)
        if not r.is_success:
            raise APIError(r.status_code, _extract_detail(r))
        return r.json()


async def upload(path: str, filename: str, content: bytes) -> Any:
    async with _client() as c:
        files = {"file": (filename, content)}
        r = await c.post(path, files=files)
        if not r.is_success:
            raise APIError(r.status_code, _extract_detail(r))
        return r.json()


def _extract_detail(r: httpx.Response) -> str:
    try:
        return r.json().get("detail", r.text)
    except Exception:
        return r.text


# ─── Convenience wrappers ─────────────────────────────────────────────────────

class ServerAPI:
    async def status(self):          return await get("/api/server/status")
    async def logs(self, n=100):     return await get("/api/server/logs", lines=n)
    async def restart(self):         return await post("/api/server/restart")
    async def reload(self):          return await post("/api/server/reload")
    async def config(self):          return await get("/api/server/config")
    async def keypair(self):         return await get("/api/server/keypair")


class ClientsAPI:
    async def list(self):                     return await get("/api/clients/")
    async def get(self, cid):                 return await get(f"/api/clients/{cid}")
    async def create(self, **kw):             return await post("/api/clients/", json=kw)
    async def update(self, cid, **kw):        return await patch(f"/api/clients/{cid}", json=kw)
    async def delete(self, cid):              return await delete(f"/api/clients/{cid}")
    async def reset_stats(self, cid):         return await post(f"/api/clients/{cid}/reset-stats")
    async def subscription(self, cid):        return await get(f"/api/clients/{cid}/subscription")


class InboundsAPI:
    async def list(self):                     return await get("/api/inbounds/")
    async def get(self, tag):                 return await get(f"/api/inbounds/{tag}")
    async def create(self, **kw):             return await post("/api/inbounds/", json=kw)
    async def update(self, tag, **kw):        return await patch(f"/api/inbounds/{tag}", json=kw)
    async def delete(self, tag):              return await delete(f"/api/inbounds/{tag}")


class RoutingAPI:
    async def get_route(self):                return await get("/api/routing/")
    async def list_rules(self, key):          return await get(f"/api/routing/rules/{key}")
    async def add_rule(self, key, val, out):  return await post("/api/routing/rules", json={"rule_key": key, "value": val, "outbound": out})
    async def del_rule(self, key, val):       return await delete("/api/routing/rules", rule_key=key, value=val)
    async def add_rule_set(self, tag, url, fmt="binary"): return await post("/api/routing/rule-sets", json={"tag": tag, "url": url, "format": fmt})
    async def del_rule_set(self, tag):        return await delete(f"/api/routing/rule-sets/{tag}")
    async def export(self):                   return await get("/api/routing/export")
    async def import_rules(self, data):       return await post("/api/routing/import", json=data)


class AdguardAPI:
    async def status(self):                   return await get("/api/adguard/status")
    async def stats(self):                    return await get("/api/adguard/stats")
    async def toggle(self, enabled):          return await post(f"/api/adguard/protection?enabled={str(enabled).lower()}")
    async def dns(self):                      return await get("/api/adguard/dns")
    async def add_upstream(self, u):          return await post("/api/adguard/dns/upstream", json={"upstream": u})
    async def del_upstream(self, u):          return await delete("/api/adguard/dns/upstream", upstream=u)
    async def rules(self):                    return await get("/api/adguard/rules")
    async def add_rule(self, r):              return await post("/api/adguard/rules", json={"rule": r})
    async def del_rule(self, r):              return await delete("/api/adguard/rules", rule=r)
    async def change_password(self, p):       return await post("/api/adguard/password", json={"password": p})
    async def sync_clients(self):             return await post("/api/adguard/sync-clients")


class NginxAPI:
    async def status(self):                   return await get("/api/nginx/status")
    async def configure(self):                return await post("/api/nginx/configure")
    async def ssl(self):                      return await post("/api/nginx/ssl")
    async def paths(self):                    return await get("/api/nginx/paths")
    async def logs(self, n=50):               return await get("/api/nginx/logs", lines=n)
    async def upload(self, filename, data):   return await upload("/api/nginx/override/upload", filename, data)
    async def delete_override(self):          return await delete("/api/nginx/override")
    async def override_status(self):          return await get("/api/nginx/override/status")


class FederationAPI:
    async def list(self):                     return await get("/api/federation/")
    async def add(self, name, url, secret, role="node"): return await post("/api/federation/", json={"name": name, "url": url, "secret": secret, "role": role})
    async def delete(self, nid):              return await delete(f"/api/federation/{nid}")
    async def ping(self, nid):                return await post(f"/api/federation/{nid}/ping")
    async def ping_all(self):                 return await post("/api/federation/ping-all")
    async def bridge(self, node_ids):         return await post("/api/federation/bridge", json={"node_ids": node_ids})
    async def topology(self):                 return await get("/api/federation/topology")


class DocsAPI:
    async def list(self):              return await get("/api/docs/")
    async def get(self, doc_id: str):  return await get_text(f"/api/docs/{doc_id}")


class AdminAPI:
    async def list_admins(self):              return await get("/api/admin/admins")
    async def add_admin(self, tg_id, uname=None): return await post("/api/admin/admins", json={"telegram_id": tg_id, "username": uname})
    async def del_admin(self, tg_id):         return await delete(f"/api/admin/admins/{tg_id}")
    async def audit_log(self, limit=50):      return await get("/api/admin/audit-log", limit=limit)
    async def backup(self):                   return await get("/api/admin/backup")


# Singletons used by handlers
docs_api      = DocsAPI()
server_api    = ServerAPI()
clients_api   = ClientsAPI()
inbounds_api  = InboundsAPI()
routing_api   = RoutingAPI()
adguard_api   = AdguardAPI()
nginx_api     = NginxAPI()
federation_api = FederationAPI()
admin_api     = AdminAPI()
