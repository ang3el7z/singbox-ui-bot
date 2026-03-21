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


async def post(path: str, json: Any = None, timeout: float | None = None, **params) -> Any:
    async with httpx.AsyncClient(base_url=_BASE, headers=_HEADERS, timeout=(timeout or 30.0)) as c:
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


async def put(path: str, json: Any = None) -> Any:
    async with _client() as c:
        r = await c.put(path, json=json)
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
    async def sub_url(self, cid):             return await get(f"/api/clients/{cid}/sub-url")


class ClientTemplatesAPI:
    async def list(self):                     return await get("/api/client-templates/")
    async def get(self, tid):                 return await get(f"/api/client-templates/{tid}")
    async def create(self, **kw):             return await post("/api/client-templates/", json=kw)
    async def update(self, tid, **kw):        return await put(f"/api/client-templates/{tid}", json=kw)
    async def delete(self, tid):              return await delete(f"/api/client-templates/{tid}")
    async def set_default(self, tid):         return await post(f"/api/client-templates/{tid}/set-default")
    async def get_default(self):              return await get("/api/client-templates/default")


class InboundsAPI:
    async def list(self):                     return await get("/api/inbounds/")
    async def get(self, tag):                 return await get(f"/api/inbounds/{tag}")
    async def create(self, **kw):             return await post("/api/inbounds/", json=kw)
    async def update(self, tag, **kw):        return await patch(f"/api/inbounds/{tag}", json=kw)
    async def delete(self, tag):              return await delete(f"/api/inbounds/{tag}")


class RoutingAPI:
    async def get_route(self):                return await get("/api/routing/")
    async def get_outbounds(self):            return await get("/api/routing/outbounds")
    async def list_rules(self, key):          return await get(f"/api/routing/rules/{key}")
    async def add_rule(self, key, val, out, download_detour="direct", update_interval="1d"):
        return await post("/api/routing/rules", json={
            "rule_key": key, "value": val, "outbound": out,
            "download_detour": download_detour, "update_interval": update_interval,
        })
    async def del_rule(self, key, val):       return await delete("/api/routing/rules", rule_key=key, value=val)
    async def add_rule_set(self, tag, url, fmt="binary"): return await post("/api/routing/rule-sets", json={"tag": tag, "url": url, "format": fmt})
    async def add_rule_set_full(self, tag, url, fmt="binary", download_detour="direct", update_interval="1d"):
        return await post("/api/routing/rule-sets", json={"tag": tag, "url": url, "format": fmt, "download_detour": download_detour, "update_interval": update_interval})
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
    async def ssl(self, email: str = ""):
        body = {"email": email} if email else {}
        return await post("/api/nginx/ssl", json=body, timeout=300.0)
    async def paths(self):                    return await get("/api/nginx/paths")
    async def logs(self, n=50):               return await get("/api/nginx/logs", lines=n)
    async def upload(self, filename, data):   return await upload("/api/nginx/override/upload", filename, data)
    async def delete_override(self):          return await delete("/api/nginx/override")
    async def override_status(self):          return await get("/api/nginx/override/status")
    async def site_toggle(self, enabled: bool): return await post(f"/api/nginx/site/toggle?enabled={str(enabled).lower()}")


class FederationAPI:
    async def list(self):                     return await get("/api/federation/")
    async def local_secret(self):             return await get("/api/federation/local-secret")
    async def add(self, name, url, secret, role="node"): return await post("/api/federation/", json={"name": name, "url": url, "secret": secret, "role": role})
    async def delete(self, nid):              return await delete(f"/api/federation/{nid}")
    async def ping(self, nid):                return await post(f"/api/federation/{nid}/ping")
    async def ping_all(self):                 return await post("/api/federation/ping-all")
    async def create_bridge(self, node_ids):  return await post("/api/federation/bridge", json={"node_ids": node_ids})
    async def topology(self):                 return await get("/api/federation/topology")


class SettingsAPI:
    async def get_all(self):               return await get("/api/settings/")
    async def get(self, key: str):         return await get(f"/api/settings/{key}")
    async def set(self, key: str, value):  return await post(f"/api/settings/{key}", json={"value": str(value)})


class DocsAPI:
    async def list(self, lang: str = "ru"):
        return await get("/api/docs/", lang=lang)
    async def get(self, doc_id: str, lang: str = "ru"):
        return await get_text(f"/api/docs/{doc_id}", lang=lang)


class AdminAPI:
    async def list_admins(self):              return await get("/api/admin/admins")
    async def add_admin(self, tg_id, uname=None): return await post("/api/admin/admins", json={"telegram_id": tg_id, "username": uname})
    async def del_admin(self, tg_id):         return await delete(f"/api/admin/admins/{tg_id}")
    async def audit_log(self, limit=50):      return await get("/api/admin/audit-log", limit=limit)
    async def backup(self):                   return await get("/api/admin/backup")


class MaintenanceAPI:
    async def status(self):
        return await get("/api/maintenance/status")

    # Backup
    async def set_backup_interval(self, hours: int):
        return await post("/api/maintenance/backup/settings", json={"hours": hours})
    async def run_backup(self):
        return await post("/api/maintenance/backup/run")
    async def backup_download_package(self) -> dict[str, Any]:
        async with _client() as c:
            r = await c.get("/api/maintenance/backup/download")
            if not r.is_success:
                raise APIError(r.status_code, _extract_detail(r))
            return {
                "content": r.content,
                "backup_path": (r.headers.get("X-Singbox-Backup-Path") or "").strip(),
            }
    async def backup_download_bytes(self) -> bytes:
        pkg = await self.backup_download_package()
        return pkg["content"]
    async def restore(self, filename: str, content: bytes, create_safety_backup: bool = True):
        async with httpx.AsyncClient(base_url=_BASE, headers=_HEADERS, timeout=120.0) as c:
            files = {"file": (filename, content, "application/zip")}
            r = await c.post(
                "/api/maintenance/restore",
                params={"create_safety_backup": str(create_safety_backup).lower()},
                files=files,
            )
            if not r.is_success:
                raise APIError(r.status_code, _extract_detail(r))
            return r.json()

    # Logs
    async def logs_list(self):
        return await get("/api/maintenance/logs/list")
    async def log_download(self, name: str) -> bytes:
        async with _client() as c:
            r = await c.get(f"/api/maintenance/logs/download/{name}")
            if not r.is_success:
                raise APIError(r.status_code, _extract_detail(r))
            return r.content
    async def log_clear_one(self, name: str):
        return await post(f"/api/maintenance/logs/clear/{name}")
    async def log_clear_all(self):
        return await post("/api/maintenance/logs/clear-all")
    async def set_log_clean_interval(self, hours: int):
        return await post("/api/maintenance/logs/settings", json={"hours": hours})

    # IP Ban
    async def ip_ban_list(self):
        return await get("/api/maintenance/ip-ban/list")
    async def ip_ban_add(self, ip: str, reason: str = "manual"):
        return await post("/api/maintenance/ip-ban/add", json={"ip": ip, "reason": reason})
    async def ip_ban_remove(self, ip: str):
        return await delete(f"/api/maintenance/ip-ban/{ip}")
    async def ip_ban_analyze(self, threshold: int = 30):
        return await post(f"/api/maintenance/ip-ban/analyze?threshold={threshold}")
    async def ip_ban_all_analyzed(self, threshold: int = 30):
        return await post(f"/api/maintenance/ip-ban/ban-analyzed?threshold={threshold}")
    async def ip_ban_clear_auto(self):
        return await post("/api/maintenance/ip-ban/clear-auto")

    # Windows Service binaries
    async def windows_binaries_status(self):
        return await get("/api/maintenance/windows/binaries-status")
    async def prefetch_windows_binaries(self):
        return await post("/api/maintenance/windows/prefetch-binaries")

    # WARP
    async def warp_status(self):
        return await get("/api/maintenance/warp/status")
    async def warp_on(self):
        return await post("/api/maintenance/warp/on")
    async def warp_off(self):
        return await post("/api/maintenance/warp/off")
    async def warp_set_key(self, license_key: str):
        return await post("/api/maintenance/warp/key", json={"license_key": license_key})
    async def warp_clear_key(self):
        return await delete("/api/maintenance/warp/key")

    # Updates
    async def update_info(self, refresh_remote: bool = True):
        return await get("/api/maintenance/update/info", refresh=str(refresh_remote).lower())
    async def update_logs(self, lines: int = 200):
        return await get("/api/maintenance/update/logs", lines=lines)
    async def update_run(
        self,
        *,
        target: str = "latest_tag",
        ref: str | None = None,
        with_backup: bool = True,
        backup_path: str | None = None,
        branch: str | None = None,  # backward-compatible
    ):
        payload: dict[str, Any] = {}
        payload["target"] = target
        payload["with_backup"] = bool(with_backup)
        if ref:
            payload["ref"] = ref
        if branch:
            payload["branch"] = branch
        if backup_path:
            payload["backup_path"] = backup_path
        return await post("/api/maintenance/update/run", json=payload, timeout=20.0)

    async def reinstall_run(
        self,
        *,
        clean: bool = True,
        target: str = "current",
        ref: str | None = None,
        with_backup: bool = True,
        backup_path: str | None = None,
    ):
        payload: dict[str, Any] = {
            "clean": bool(clean),
            "target": target,
            "with_backup": bool(with_backup),
        }
        if ref:
            payload["ref"] = ref
        if backup_path:
            payload["backup_path"] = backup_path
        return await post("/api/maintenance/reinstall/run", json=payload, timeout=20.0)
    async def update_cleanup(self):
        return await post("/api/maintenance/update/cleanup")


# Singletons used by handlers
settings_api     = SettingsAPI()
docs_api         = DocsAPI()
server_api       = ServerAPI()
clients_api      = ClientsAPI()
client_tmpl_api  = ClientTemplatesAPI()
inbounds_api     = InboundsAPI()
routing_api      = RoutingAPI()
adguard_api      = AdguardAPI()
nginx_api        = NginxAPI()
federation_api   = FederationAPI()
admin_api        = AdminAPI()
maintenance_api  = MaintenanceAPI()
