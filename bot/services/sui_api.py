"""
HTTP client for s-ui REST API (v2 token-based).
Docs: s-ui-main/api/apiV2Handler.go
"""
import httpx
from typing import Any, Dict, List, Optional
from api.config import settings


class SuiAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class SuiAPI:
    def __init__(self):
        self.base_url = settings.sui_url.rstrip("/")
        self._token: Optional[str] = settings.sui_token or None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0, verify=False)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _ensure_token(self) -> str:
        if self._token:
            return self._token
        await self._login()
        return self._token

    async def _login(self) -> None:
        client = await self._get_client()
        resp = await client.post(
            f"{self.base_url}/api/login",
            json={"username": settings.sui_username, "password": settings.sui_password},
        )
        if resp.status_code != 200:
            raise SuiAPIError(f"Login failed: {resp.text}", resp.status_code)
        data = resp.json()
        if not data.get("success"):
            raise SuiAPIError(f"Login failed: {data.get('msg', 'unknown')}")
        # After session login, get a bearer token
        token_resp = await client.post(
            f"{self.base_url}/api/addToken",
            json={"remark": "singbox-bot"},
        )
        if token_resp.status_code == 200 and token_resp.json().get("success"):
            tokens = token_resp.json().get("obj", [])
            if tokens:
                self._token = tokens[-1].get("token")

    def _headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        token = await self._ensure_token()
        client = await self._get_client()
        resp = await client.get(
            f"{self.base_url}/apiv2/{path}",
            headers=self._headers(token),
            params=params,
        )
        if resp.status_code == 401:
            self._token = None
            token = await self._ensure_token()
            resp = await client.get(
                f"{self.base_url}/apiv2/{path}",
                headers=self._headers(token),
                params=params,
            )
        if resp.status_code != 200:
            raise SuiAPIError(f"GET {path} failed: {resp.text}", resp.status_code)
        data = resp.json()
        if not data.get("success", True):
            raise SuiAPIError(data.get("msg", "API error"))
        return data.get("obj", data)

    async def _post(self, path: str, payload: Any = None) -> Any:
        token = await self._ensure_token()
        client = await self._get_client()
        resp = await client.post(
            f"{self.base_url}/apiv2/{path}",
            headers=self._headers(token),
            json=payload,
        )
        if resp.status_code == 401:
            self._token = None
            token = await self._ensure_token()
            resp = await client.post(
                f"{self.base_url}/apiv2/{path}",
                headers=self._headers(token),
                json=payload,
            )
        if resp.status_code != 200:
            raise SuiAPIError(f"POST {path} failed: {resp.text}", resp.status_code)
        data = resp.json()
        if not data.get("success", True):
            raise SuiAPIError(data.get("msg", "API error"))
        return data.get("obj", data)

    # ─── Status & server ───────────────────────────────────────────────────────

    async def get_status(self, full: bool = False) -> Dict:
        return await self._get("status", {"r": "true" if full else "false"})

    async def get_logs(self, count: int = 50, level: str = "info") -> List[str]:
        raw = await self._get("logs", {"c": str(count), "l": level})
        if isinstance(raw, list):
            return raw
        return raw.get("logs", [])

    async def restart_singbox(self) -> bool:
        await self._post("restartSb")
        return True

    async def restart_panel(self) -> bool:
        await self._post("restartApp")
        return True

    # ─── Full load ─────────────────────────────────────────────────────────────

    async def load(self) -> Dict:
        """Returns full config: config, clients, tls, inbounds, outbounds, endpoints, services, subURI, onlines."""
        return await self._get("load")

    # ─── Clients ───────────────────────────────────────────────────────────────

    async def get_clients(self, client_id: Optional[int] = None) -> Any:
        params = {"id": str(client_id)} if client_id else None
        return await self._get("clients", params)

    async def save_client(self, client_data: Dict) -> Any:
        return await self._post("save", {"object": "client", "action": "save", "data": client_data})

    async def delete_client(self, client_id: int) -> Any:
        return await self._post("save", {"object": "client", "action": "delete", "data": {"id": client_id}})

    async def reset_client_stats(self, client_id: int) -> Any:
        return await self._post("save", {"object": "client", "action": "resetStats", "data": {"id": client_id}})

    # ─── Inbounds ──────────────────────────────────────────────────────────────

    async def get_inbounds(self, inbound_id: Optional[int] = None) -> Any:
        params = {"id": str(inbound_id)} if inbound_id else None
        return await self._get("inbounds", params)

    async def save_inbound(self, inbound_data: Dict) -> Any:
        return await self._post("save", {"object": "inbound", "action": "save", "data": inbound_data})

    async def delete_inbound(self, inbound_id: int) -> Any:
        return await self._post("save", {"object": "inbound", "action": "delete", "data": {"id": inbound_id}})

    async def toggle_inbound(self, inbound_id: int, enable: bool) -> Any:
        return await self._post("save", {
            "object": "inbound",
            "action": "save",
            "data": {"id": inbound_id, "enable": enable},
        })

    # ─── Outbounds ─────────────────────────────────────────────────────────────

    async def get_outbounds(self) -> Any:
        return await self._get("outbounds")

    async def save_outbound(self, outbound_data: Dict) -> Any:
        return await self._post("save", {"object": "outbound", "action": "save", "data": outbound_data})

    async def delete_outbound(self, outbound_id: int) -> Any:
        return await self._post("save", {"object": "outbound", "action": "delete", "data": {"id": outbound_id}})

    # ─── Stats ─────────────────────────────────────────────────────────────────

    async def get_stats(
        self,
        resource: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ) -> Any:
        params: Dict[str, str] = {"limit": str(limit)}
        if resource:
            params["resource"] = resource
        if tag:
            params["tag"] = tag
        return await self._get("stats", params)

    async def get_onlines(self) -> Any:
        return await self._get("onlines")

    # ─── Config / Settings ─────────────────────────────────────────────────────

    async def get_config(self) -> Dict:
        return await self._get("config")

    async def get_settings(self) -> Dict:
        return await self._get("settings")

    async def save_settings(self, settings_data: Dict) -> Any:
        return await self._post("save", {"object": "setting", "action": "save", "data": settings_data})

    async def get_tls(self) -> Any:
        return await self._get("tls")

    async def save_tls(self, tls_data: Dict) -> Any:
        return await self._post("save", {"object": "tls", "action": "save", "data": tls_data})

    # ─── Subscriptions ─────────────────────────────────────────────────────────

    async def get_subscription(self, sub_id: str, fmt: str = "json") -> str:
        client = await self._get_client()
        url = f"{self.base_url}/sub/{sub_id}"
        params = {"format": fmt} if fmt != "default" else {}
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            raise SuiAPIError(f"Subscription fetch failed: {resp.text}", resp.status_code)
        return resp.text

    # ─── Keypairs ──────────────────────────────────────────────────────────────

    async def generate_keypair(self, key_type: str = "reality") -> Dict:
        return await self._get("keypairs", {"k": key_type})

    # ─── Changes ───────────────────────────────────────────────────────────────

    async def get_changes(self, action: Optional[str] = None) -> Any:
        params = {}
        if action:
            params["a"] = action
        return await self._get("changes", params if params else None)

    # ─── Endpoints & Services ──────────────────────────────────────────────────

    async def get_endpoints(self) -> Any:
        return await self._get("endpoints")

    async def get_services(self) -> Any:
        return await self._get("services")


# Singleton instance
sui = SuiAPI()
