"""
Bot Federation Service.
Each bot exposes a small FastAPI over /federation/ for inter-bot communication.
All requests are signed with HMAC-SHA256 using FEDERATION_SECRET.

Bridge mode: Bot A → (outbound) → Bot B → (outbound) → Bot C → Internet
Node mode:   Bot B exposes its inbounds as outbounds for Bot A's users.
"""
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel

from api.config import settings
from api.database import async_session, FederationNode
from api.services.singbox import singbox
from sqlalchemy import select


# ─── HMAC helpers ─────────────────────────────────────────────────────────────

def sign_payload(payload: dict, secret: str) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256)
    return mac.hexdigest()


def verify_signature(payload: dict, signature: str, secret: str) -> bool:
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(expected, signature)


def make_signed_request(payload: dict, secret: str) -> dict:
    ts = int(time.time())
    payload["_ts"] = ts
    sig = sign_payload(payload, secret)
    return {"payload": payload, "signature": sig}


def verify_signed_request(data: dict, secret: str) -> dict:
    payload = data.get("payload", {})
    signature = data.get("signature", "")
    ts = payload.get("_ts", 0)
    if abs(time.time() - ts) > 300:  # 5 min window
        raise ValueError("Request timestamp expired")
    if not verify_signature(payload, signature, secret):
        raise ValueError("Invalid HMAC signature")
    return payload


# ─── FastAPI Federation Router ────────────────────────────────────────────────

fed_router = APIRouter(prefix="/federation")


class NodeInfoResponse(BaseModel):
    name: str
    version: str = "1.0"
    public_url: str
    protocols: List[str]


class InboundShareRequest(BaseModel):
    payload: dict
    signature: str


@fed_router.get("/info")
async def fed_info():
    """Public info about this node (no auth required)."""
    return NodeInfoResponse(
        name=settings.domain or "singbox-node",
        public_url=settings.bot_public_url,
        protocols=["vless", "vmess", "shadowsocks", "trojan", "hysteria2", "tuic"],
    )


@fed_router.post("/ping")
async def fed_ping(request: Request):
    """Authenticated ping to verify connectivity."""
    data = await request.json()
    try:
        payload = verify_signed_request(data, settings.federation_secret)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"pong": True, "ts": int(time.time()), "from": payload.get("from", "?")}


@fed_router.post("/inbounds")
async def fed_get_inbounds(request: Request):
    """Return inbound configs for bridging (authenticated)."""
    data = await request.json()
    try:
        verify_signed_request(data, settings.federation_secret)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    try:
        inbounds = singbox.get_inbounds()
        public_inbounds = []
        for ib in (inbounds if isinstance(inbounds, list) else []):
            if ib.get("enable", True):
                public_inbounds.append({
                    "tag": ib.get("tag"),
                    "type": ib.get("type"),
                    "port": ib.get("listen_port"),
                    "host": settings.domain,
                })
        return {"inbounds": public_inbounds}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@fed_router.post("/add_outbound")
async def fed_add_outbound(request: Request):
    """Add an outbound to this node (for bridge setup)."""
    data = await request.json()
    try:
        payload = verify_signed_request(data, settings.federation_secret)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    outbound_data = payload.get("outbound")
    if not outbound_data:
        raise HTTPException(status_code=400, detail="Missing outbound data")
    try:
        singbox.save_outbound(outbound_data)
        await singbox.reload()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Federation client (calls remote nodes) ───────────────────────────────────

class FederationClient:
    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=15.0, verify=False)
        return self._http

    def _signed(self, payload: dict, secret: str) -> dict:
        return make_signed_request(payload, secret)

    async def ping_node(self, node_url: str, secret: str) -> bool:
        client = await self._client()
        payload = self._signed({"from": settings.domain}, secret)
        try:
            resp = await client.post(f"{node_url.rstrip('/')}/federation/ping", json=payload, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    async def get_remote_inbounds(self, node_url: str, secret: str) -> List[Dict]:
        client = await self._client()
        payload = self._signed({"from": settings.domain}, secret)
        resp = await client.post(f"{node_url.rstrip('/')}/federation/inbounds", json=payload)
        if resp.status_code != 200:
            raise ValueError(f"Remote node error: {resp.text}")
        return resp.json().get("inbounds", [])

    async def add_outbound_to_node(self, node_url: str, secret: str, outbound: dict) -> bool:
        client = await self._client()
        payload = self._signed({"from": settings.domain, "outbound": outbound}, secret)
        resp = await client.post(f"{node_url.rstrip('/')}/federation/add_outbound", json=payload)
        return resp.status_code == 200

    async def get_all_nodes(self) -> List[Dict]:
        async with async_session() as session:
            result = await session.execute(select(FederationNode))
            nodes = result.scalars().all()
            return [
                {
                    "id": n.id,
                    "name": n.name,
                    "url": n.url,
                    "secret": n.secret,
                    "is_active": n.is_active,
                    "last_ping": n.last_ping,
                    "role": n.role,
                }
                for n in nodes
            ]

    async def ping_all_nodes(self) -> List[Dict]:
        nodes = await self.get_all_nodes()
        results = []
        for node in nodes:
            online = await self.ping_node(node["url"], node["secret"])
            from datetime import datetime
            async with async_session() as session:
                db_node = await session.get(FederationNode, node["id"])
                if db_node:
                    db_node.last_ping = datetime.utcnow() if online else db_node.last_ping
                    db_node.is_active = online
                    await session.commit()
            results.append({**node, "online": online})
        return results

    async def create_bridge(self, node_chain: List[Dict]) -> bool:
        """
        Set up a bridge chain: node_chain[0] → node_chain[1] → ... → Internet
        Each node gets an outbound pointing to the next node in the chain.
        """
        if len(node_chain) < 1:
            raise ValueError("Bridge requires at least 1 node")

        if len(node_chain) == 1:
            # Single node: add local outbound pointing directly to that node
            next_inbounds = await self.get_remote_inbounds(node_chain[0]["url"], node_chain[0]["secret"])
            if not next_inbounds:
                raise ValueError(f"Node {node_chain[0]['name']} has no available inbounds")
            outbound = _build_outbound_for_inbound(next_inbounds[0], tag=f"exit_{node_chain[0]['name']}")
            singbox.save_outbound(outbound)
            await singbox.reload()
            return True

        # Multi-hop: The final node (exit) doesn't need a new outbound
        # Nodes from 0 to N-2 each need an outbound to the next
        for i in range(len(node_chain) - 1):
            current_node = node_chain[i]
            next_node = node_chain[i + 1]

            # Get next node's inbounds to pick one as the outbound target
            next_inbounds = await self.get_remote_inbounds(next_node["url"], next_node["secret"])
            if not next_inbounds:
                raise ValueError(f"Node {next_node['name']} has no available inbounds")

            # Use first available inbound of next node
            target = next_inbounds[0]
            outbound = _build_outbound_for_inbound(target, tag=f"bridge_to_{next_node['name']}")

            if i == 0:
                # Add outbound to local Sing-Box
                singbox.save_outbound(outbound)
                await singbox.reload()
            else:
                # Add outbound to remote current_node
                await self.add_outbound_to_node(current_node["url"], current_node["secret"], outbound)

        return True


def _build_outbound_for_inbound(inbound: dict, tag: str) -> dict:
    """Build a minimal outbound config that connects to a remote inbound."""
    proto = inbound.get("type", "vless")
    host = inbound.get("host", "")
    port = inbound.get("port", 443)

    base = {"tag": tag, "type": proto, "server": host, "server_port": port}

    if proto == "vless":
        base["uuid"] = ""  # To be filled by admin
        base["tls"] = {"enabled": True, "server_name": host}
    elif proto == "shadowsocks":
        base["method"] = "aes-256-gcm"
        base["password"] = ""
    elif proto == "trojan":
        base["password"] = ""
        base["tls"] = {"enabled": True, "server_name": host}

    return base


fed_client = FederationClient()
