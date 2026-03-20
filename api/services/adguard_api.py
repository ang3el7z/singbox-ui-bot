"""
AdGuard Home REST API client.
API docs: https://github.com/AdguardTeam/AdGuardHome/tree/master/openapi
"""
import asyncio
import re
from pathlib import Path

import httpx
from typing import Any, Dict, List, Optional
from api.config import settings
from api.services import docker_engine


class AdGuardAPIError(Exception):
    pass


BASE_DIR = Path(__file__).parent.parent.parent
PASSWORD_FILE = BASE_DIR / "data" / "adguard_admin_password"


class AdGuardAPI:
    def __init__(self):
        self.base_url = settings.adguard_url.rstrip("/")
        self.auth = (settings.adguard_user, self._load_password())
        self._client: Optional[httpx.AsyncClient] = None

    def _load_password(self) -> str:
        if PASSWORD_FILE.exists():
            return PASSWORD_FILE.read_text(encoding="utf-8").strip() or settings.adguard_password
        return settings.adguard_password

    def _store_password(self, password: str) -> None:
        PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
        PASSWORD_FILE.write_text(password, encoding="utf-8")

    async def _restart_container(self) -> None:
        try:
            await asyncio.to_thread(
                docker_engine.restart_container,
                settings.adguard_container,
                timeout=20,
            )
        except Exception as e:
            raise AdGuardAPIError(f"Failed to restart {settings.adguard_container}: {e}") from e

    async def bootstrap_admin_password(self) -> bool:
        """
        Seed the first AdGuard admin password into AdGuardHome.yaml if it is still empty.

        This makes install.sh's generated ADGUARD_PASSWORD real on first boot.
        """
        config_path = Path(settings.adguard_config_path)
        if not settings.adguard_password or not config_path.exists():
            return False

        raw = config_path.read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*password\s*:\s*\S+", raw):
            return False

        match = re.search(r"(?m)^(\s*-\s*name\s*:\s*admin\s*)$", raw)
        if not match:
            return False

        import bcrypt

        pwd_hash = bcrypt.hashpw(settings.adguard_password.encode(), bcrypt.gensalt()).decode()
        indent = re.match(r"^\s*", match.group(1)).group(0) + "  "
        injected = f"{match.group(0)}\n{indent}password: {pwd_hash}"
        updated = raw[:match.start()] + injected + raw[match.end():]
        if updated == raw:
            return False

        config_path.write_text(updated, encoding="utf-8")
        self._store_password(settings.adguard_password)
        self.auth = (settings.adguard_user, settings.adguard_password)
        await self.close()
        await self._restart_container()
        return True

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0, auth=self.auth, verify=False)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/control/{path}", params=params)
        if resp.status_code not in (200, 204):
            raise AdGuardAPIError(f"GET {path} failed [{resp.status_code}]: {resp.text}")
        if resp.content:
            return resp.json()
        return {}

    async def _post(self, path: str, payload: Any = None, data: Optional[str] = None) -> Any:
        client = await self._get_client()
        if data is not None:
            resp = await client.post(f"{self.base_url}/control/{path}", content=data)
        else:
            resp = await client.post(f"{self.base_url}/control/{path}", json=payload)
        if resp.status_code not in (200, 204):
            raise AdGuardAPIError(f"POST {path} failed [{resp.status_code}]: {resp.text}")
        if resp.content:
            try:
                return resp.json()
            except Exception:
                return resp.text
        return {}

    # ─── Status ─────────────────────────────────────────────────────────────────

    async def get_status(self) -> Dict:
        return await self._get("status")

    async def enable_protection(self, enabled: bool) -> None:
        await self._post("dns_config", {"protection_enabled": enabled})

    # ─── Stats ──────────────────────────────────────────────────────────────────

    async def get_stats(self) -> Dict:
        return await self._get("stats")

    async def reset_stats(self) -> None:
        await self._post("stats_reset")

    # ─── Query Log ──────────────────────────────────────────────────────────────

    async def get_query_log(self, limit: int = 50) -> Dict:
        return await self._get("querylog", {"limit": str(limit)})

    # ─── DNS Config ─────────────────────────────────────────────────────────────

    async def get_dns_info(self) -> Dict:
        return await self._get("dns_info")

    async def set_upstream_dns(self, upstreams: List[str]) -> None:
        await self._post("set_upstreams_config", {
            "upstream_dns": upstreams,
            "fallback_dns": [],
            "bootstrap_dns": ["8.8.8.8", "1.1.1.1"],
        })

    async def test_upstream_dns(self, upstreams: List[str]) -> Dict:
        return await self._post("test_upstream_dns", {"upstream_dns": upstreams})

    # ─── Filtering rules ────────────────────────────────────────────────────────

    async def get_filtering_status(self) -> Dict:
        return await self._get("filtering/status")

    async def add_filter_rule(self, rule: str) -> None:
        """Add a custom filtering rule (AdBlock syntax)."""
        status = await self.get_filtering_status()
        rules = status.get("user_rules", [])
        if rule not in rules:
            rules.append(rule)
        await self._post("filtering/set_rules", {"rules": rules})

    async def remove_filter_rule(self, rule: str) -> None:
        status = await self.get_filtering_status()
        rules = [r for r in status.get("user_rules", []) if r != rule]
        await self._post("filtering/set_rules", {"rules": rules})

    async def get_user_rules(self) -> List[str]:
        status = await self.get_filtering_status()
        return status.get("user_rules", [])

    async def enable_filtering(self, enabled: bool) -> None:
        await self._post("filtering/config", {"enabled": enabled, "interval": 24})

    # ─── Clients ────────────────────────────────────────────────────────────────

    async def get_clients(self) -> List[Dict]:
        result = await self._get("clients")
        return result.get("clients", [])

    async def add_client(self, client: Dict) -> None:
        await self._post("clients/add", client)

    async def delete_client(self, name: str) -> None:
        await self._post("clients/delete", {"name": name})

    async def update_client(self, name: str, data: Dict) -> None:
        await self._post("clients/update", {"name": name, "data": data})

    # ─── Password change ─────────────────────────────────────────────────────────

    async def change_password(self, new_password: str) -> None:
        """Change AdGuard Home admin password."""
        import bcrypt
        pwd_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        await self._post("profile/update", {"password_hash": pwd_hash})
        self.auth = (settings.adguard_user, new_password)
        self._store_password(new_password)
        await self.close()

    # ─── Safe browsing / parental ────────────────────────────────────────────────

    async def get_safe_browsing_status(self) -> Dict:
        return await self._get("safebrowsing/status")

    async def enable_safe_browsing(self, enabled: bool) -> None:
        path = "safebrowsing/enable" if enabled else "safebrowsing/disable"
        await self._post(path)


# Singleton
adguard = AdGuardAPI()
