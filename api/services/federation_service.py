"""
Bot Federation Service.

Each singbox-ui-bot exposes /federation/* endpoints for inter-server communication.
All requests are signed with HMAC-SHA256 using FEDERATION_SECRET.

--- How bridging works ---

A bridge routes traffic from Server A through one or more intermediate servers to the Internet.

Single-hop (direct exit):
  Server A  ──(outbound: exit_B)──▶  Server B  ──▶  Internet

Multi-hop (bridge chain):
  Server A  ──(outbound: hop_B)──▶  Server B  ──(outbound: hop_C)──▶  Server C  ──▶  Internet

Setup flow for A→B:
  1. A calls B's POST /federation/provision_client
     B creates a new sing-box client (UUID + credentials) on its first active inbound
     B returns: {type, host, port, uuid, password, tls settings}
  2. A builds a proper outbound from those credentials
  3. A adds the outbound locally as `exit_B`
  4. A can now route traffic rules to `exit_B`

Setup flow for A→B→C:
  1. A→C: provision_client → A gets creds for C
  2. A→B: provision_client → A gets creds for B (A's local outbound to B = `hop_B`)
  3. A→B: add_outbound     → B gets an outbound to C using C's credentials (`hop_C` on B)
  4. A can now route to `hop_B` and traffic flows A→B→C→Internet
"""
import hashlib
import hmac
import json
import secrets
import time
import uuid as uuid_lib
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.config import settings
from api.routers.settings_router import get_runtime
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


@fed_router.get("/info")
async def fed_info():
    """Public info about this node (no auth required)."""
    return NodeInfoResponse(
        name=get_runtime("domain") or "singbox-node",
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
    """Return list of available inbounds (authenticated)."""
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
                    "host": get_runtime("domain"),
                })
        return {"inbounds": public_inbounds}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@fed_router.post("/provision_client")
async def fed_provision_client(request: Request):
    """
    Create a dedicated bridge client on this node and return its credentials.

    Caller (another singbox-ui-bot) will use the returned data to build
    an outbound that routes traffic through this node.

    Returns full connection details: type, host, port, uuid/password, TLS settings.
    """
    data = await request.json()
    try:
        payload = verify_signed_request(data, settings.federation_secret)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    client_name = payload.get("client_name", "bridge_client")
    inbound_tag  = payload.get("inbound_tag")   # optional: pick specific inbound

    # Pick inbound: explicit tag or first active one
    inbounds = singbox.get_inbounds()
    active = [ib for ib in inbounds if ib.get("enable", True)]
    if not active:
        raise HTTPException(status_code=503, detail="No active inbounds on this node")

    if inbound_tag:
        ib = next((i for i in active if i.get("tag") == inbound_tag), None)
        if not ib:
            raise HTTPException(status_code=404, detail=f"Inbound '{inbound_tag}' not found")
    else:
        ib = active[0]

    proto = ib.get("type", "vless")
    domain = get_runtime("domain") or ""
    port = ib.get("listen_port", 443)
    tls = ib.get("tls", {})

    # Generate credentials
    new_uuid = str(uuid_lib.uuid4())
    new_password = secrets.token_hex(16)

    # Add user to inbound
    if proto in ("vless", "vmess", "tuic"):
        user = {"name": client_name, "uuid": new_uuid}
    elif proto in ("trojan", "hysteria2"):
        user = {"name": client_name, "password": new_password}
    elif proto == "shadowsocks":
        # Shadowsocks: one user = one inbound; return existing method/password
        user = None  # no per-user management for SS
        new_password = ib.get("password", new_password)
    else:
        user = {"name": client_name, "uuid": new_uuid}

    if user is not None:
        singbox.add_user_to_inbound(ib["tag"], user)
        await singbox.reload()

    # Build response with all connection info needed to construct an outbound
    result: dict = {
        "inbound_tag": ib["tag"],
        "type": proto,
        "host": domain,
        "port": port,
        "client_name": client_name,
    }

    if proto in ("vless", "vmess", "tuic"):
        result["uuid"] = new_uuid
    if proto in ("trojan", "hysteria2", "shadowsocks"):
        result["password"] = new_password
    if proto == "shadowsocks":
        result["method"] = ib.get("method", "aes-256-gcm")
    if tls.get("enabled"):
        tls_out: dict = {"enabled": True, "server_name": tls.get("server_name", domain)}
        reality = tls.get("reality", {})
        if reality.get("enabled"):
            tls_out["reality"] = {
                "enabled": True,
                "public_key": reality.get("public_key", ""),
                "short_id": (reality.get("short_id") or [""])[0],
            }
            tls_out["utls"] = {"enabled": True, "fingerprint": "chrome"}
            # VLESS Reality requires flow
            if proto == "vless":
                result["flow"] = "xtls-rprx-vision"
        result["tls"] = tls_out
    transport = ib.get("transport", {})
    if transport.get("type") == "ws":
        result["transport"] = {"type": "ws", "path": transport.get("path", "/")}

    return result


@fed_router.post("/add_outbound")
async def fed_add_outbound(request: Request):
    """Add an outbound to this node (for multi-hop bridge setup)."""
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


# ─── Outbound builder ─────────────────────────────────────────────────────────

def build_outbound_from_provision(provision: dict, tag: str) -> dict:
    """
    Build a complete sing-box outbound from a /provision_client response.
    All credentials and TLS settings are populated.
    """
    proto = provision["type"]
    ob: dict = {
        "tag":         tag,
        "type":        proto,
        "server":      provision["host"],
        "server_port": provision["port"],
    }
    if proto in ("vless", "vmess", "tuic"):
        ob["uuid"] = provision["uuid"]
    if proto in ("trojan", "hysteria2"):
        ob["password"] = provision["password"]
    if proto == "shadowsocks":
        ob["method"]   = provision.get("method", "aes-256-gcm")
        ob["password"] = provision["password"]
    if provision.get("flow"):
        ob["flow"] = provision["flow"]
    if provision.get("tls"):
        ob["tls"] = provision["tls"]
    if provision.get("transport"):
        ob["transport"] = provision["transport"]
    if proto == "tuic":
        ob["congestion_control"] = "bbr"
    return ob


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
        payload = self._signed({"from": get_runtime("domain")}, secret)
        try:
            resp = await client.post(
                f"{node_url.rstrip('/')}/federation/ping", json=payload, timeout=10
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def get_remote_inbounds(self, node_url: str, secret: str) -> List[Dict]:
        client = await self._client()
        payload = self._signed({"from": get_runtime("domain")}, secret)
        resp = await client.post(
            f"{node_url.rstrip('/')}/federation/inbounds", json=payload
        )
        if resp.status_code != 200:
            raise ValueError(f"Remote node error: {resp.text}")
        return resp.json().get("inbounds", [])

    async def provision_client(
        self,
        node_url: str,
        secret: str,
        client_name: str,
        inbound_tag: Optional[str] = None,
    ) -> dict:
        """
        Ask the remote node to create a bridge client and return its credentials.
        Returns a dict that can be passed to build_outbound_from_provision().
        """
        client = await self._client()
        p: dict = {
            "from": get_runtime("domain"),
            "client_name": client_name,
        }
        if inbound_tag:
            p["inbound_tag"] = inbound_tag
        payload = self._signed(p, secret)
        resp = await client.post(
            f"{node_url.rstrip('/')}/federation/provision_client", json=payload, timeout=30
        )
        if resp.status_code != 200:
            raise ValueError(f"Provision failed on {node_url}: {resp.text}")
        return resp.json()

    async def add_outbound_to_node(
        self, node_url: str, secret: str, outbound: dict
    ) -> bool:
        client = await self._client()
        payload = self._signed(
            {"from": get_runtime("domain"), "outbound": outbound}, secret
        )
        resp = await client.post(
            f"{node_url.rstrip('/')}/federation/add_outbound", json=payload
        )
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

    async def create_bridge(self, node_chain: List[Dict]) -> dict:
        """
        Set up a bridge chain: (this server) → node_chain[0] → ... → node_chain[-1] → Internet

        For each hop we call /provision_client on the target node to get real credentials,
        then add the outbound either locally or to the previous hop's node.

        Returns a summary of created outbounds.
        """
        if len(node_chain) < 1:
            raise ValueError("Bridge requires at least 1 node")

        domain = get_runtime("domain") or "local"
        created = []

        if len(node_chain) == 1:
            # Single-hop: local outbound → exit node
            node = node_chain[0]
            client_name = f"bridge_from_{domain[:20]}"
            provision = await self.provision_client(node["url"], node["secret"], client_name)
            outbound = build_outbound_from_provision(provision, tag=f"exit_{node['name']}")
            singbox.save_outbound(outbound)
            await singbox.reload()
            created.append({"server": "local", "outbound_tag": outbound["tag"]})
            return {"created": created, "chain": f"(this server) → {node['name']} → Internet"}

        # Multi-hop: A → B → C → Internet
        # Step 1: For each consecutive pair (i, i+1), provision a client on node[i+1]
        #         and add the outbound to node[i] (or locally for i==0)
        for i in range(len(node_chain)):
            current = node_chain[i]
            if i < len(node_chain) - 1:
                # Need an outbound on node[i] pointing to node[i+1]
                next_node = node_chain[i + 1]
                client_name = f"bridge_from_{current['name'][:15]}"
                provision = await self.provision_client(
                    next_node["url"], next_node["secret"], client_name
                )
                outbound_tag = f"hop_{next_node['name']}"
                outbound = build_outbound_from_provision(provision, tag=outbound_tag)

                if i == 0:
                    # Add outbound to THIS server (first hop is always local)
                    singbox.save_outbound(outbound)
                    await singbox.reload()
                    created.append({"server": "local", "outbound_tag": outbound_tag})
                else:
                    # Add outbound to node[i] (intermediate bridge node)
                    ok = await self.add_outbound_to_node(
                        current["url"], current["secret"], outbound
                    )
                    if not ok:
                        raise ValueError(f"Failed to add outbound to node {current['name']}")
                    created.append({"server": current["name"], "outbound_tag": outbound_tag})

        chain = " → ".join(["(this server)"] + [n["name"] for n in node_chain] + ["Internet"])
        return {"created": created, "chain": chain}


fed_client = FederationClient()
