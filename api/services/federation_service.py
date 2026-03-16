"""
Bot Federation Service.

Each singbox-ui-bot exposes /federation/* endpoints for inter-server communication.
All requests are signed with HMAC-SHA256 using FEDERATION_SECRET.

--- How bridging works ---

A bridge routes traffic from Server A through one or more intermediate servers to the Internet.

Single-hop (direct exit):
  Server A  ──(outbound: exit_B)──▶  Server B  ──▶  Internet

Multi-hop (bridge chain):
  Server A  ──(outbound: bridge_to_B)──▶  Server B  ──(outbound: bridge_to_C)──▶  Server C  ──▶  Internet

Setup flow for A→B:
  1. A calls B's POST /federation/provision_client
     B creates a new sing-box client (UUID + credentials) on its first active inbound
     B returns: {type, host, port, uuid, password, tls settings}
  2. A builds a proper outbound from those credentials
  3. A adds the outbound locally as `exit_B`
  4. A can now route traffic rules to `exit_B`

Setup flow for A→B→C:
  1. A→B: provision_client → A gets creds for B (A's local outbound = `bridge_to_B`)
  2. A→C: provision_client → A gets creds for C
  3. A→B: add_outbound     → B gets an outbound to C using C's credentials (`bridge_to_C` on B)
  4. B routes `auth_user=<bridge client>` to `bridge_to_C`
  5. A can now route to `bridge_to_B` and traffic flows A→B→C→Internet
"""
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid as uuid_lib
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

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


def _normalize_peer_id(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = parsed.netloc or parsed.path
    return host.split("@")[-1].split("/")[0].strip("/")


def _local_peer_id() -> str:
    return (
        _normalize_peer_id(get_runtime("domain"))
        or _normalize_peer_id(settings.bot_public_url)
        or "local"
    )


def _unique_preserve(values: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _safe_tag_fragment(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return cleaned.strip("-") or "node"


def _bridge_outbound_tag(node_name: str) -> str:
    return f"bridge_to_{_safe_tag_fragment(node_name)}"


def _entry_outbound_tag(node_chain: List[Dict]) -> str:
    first = node_chain[0]
    if len(node_chain) == 1:
        return f"exit_{_safe_tag_fragment(first['name'])}"
    return _bridge_outbound_tag(first["name"])


def _bridge_client_name(local_id: str, node_chain: List[Dict], hop_index: int, node_name: str) -> str:
    chain_key = "->".join(_safe_tag_fragment(n["name"]) for n in node_chain)
    digest = hashlib.sha1(f"{local_id}|{chain_key}|{hop_index}|{node_name}".encode()).hexdigest()[:10]
    return f"bridge_{hop_index}_{digest}"


async def verify_federation_request(data: dict) -> dict:
    payload = data.get("payload", {})
    signature = data.get("signature", "")
    ts = payload.get("_ts", 0)
    if abs(time.time() - ts) > 300:
        raise ValueError("Request timestamp expired")

    candidates: List[str] = []
    peer_id = _normalize_peer_id(payload.get("from"))
    if peer_id:
        async with async_session() as session:
            result = await session.execute(select(FederationNode))
            for node in result.scalars().all():
                if peer_id in {
                    _normalize_peer_id(node.url),
                    _normalize_peer_id(node.name),
                }:
                    candidates.append(node.secret)

    candidates.append(settings.federation_secret)
    for secret in _unique_preserve(candidates):
        if verify_signature(payload, signature, secret):
            return payload
    raise ValueError("Invalid HMAC signature")


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
        payload = await verify_federation_request(data)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"pong": True, "ts": int(time.time()), "from": payload.get("from", "?")}


@fed_router.post("/inbounds")
async def fed_get_inbounds(request: Request):
    """Return list of available inbounds (authenticated)."""
    data = await request.json()
    try:
        await verify_federation_request(data)
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
        payload = await verify_federation_request(data)
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
        payload = await verify_federation_request(data)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    outbound_data = payload.get("outbound")
    auth_user = payload.get("auth_user")
    if not outbound_data:
        raise HTTPException(status_code=400, detail="Missing outbound data")
    try:
        singbox.save_outbound(outbound_data)
        if auth_user:
            singbox.upsert_auth_user_route(str(auth_user), outbound_data["tag"])
        await singbox.reload()
        return {"success": True, "outbound_tag": outbound_data["tag"], "auth_user": auth_user}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@fed_router.post("/remove_link")
async def fed_remove_link(request: Request):
    """Remove a bridge outbound and its auth_user routing rule from this node."""
    data = await request.json()
    try:
        payload = await verify_federation_request(data)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    outbound_tag = str(payload.get("outbound_tag") or "").strip()
    auth_user = str(payload.get("auth_user") or "").strip()
    if not outbound_tag:
        raise HTTPException(status_code=400, detail="Missing outbound_tag")

    try:
        removed_outbound = singbox.delete_outbound(outbound_tag)
        removed_rule = False
        if auth_user:
            removed_rule = singbox.remove_auth_user_route(auth_user, outbound_tag)
        if removed_outbound or removed_rule:
            await singbox.reload()
        return {
            "success": True,
            "removed_outbound": removed_outbound,
            "removed_rule": removed_rule,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@fed_router.post("/revoke_client")
async def fed_revoke_client(request: Request):
    """Remove a previously provisioned bridge client from an inbound."""
    data = await request.json()
    try:
        payload = await verify_federation_request(data)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    inbound_tag = str(payload.get("inbound_tag") or "").strip()
    client_name = str(payload.get("client_name") or "").strip()
    if not inbound_tag or not client_name:
        raise HTTPException(status_code=400, detail="Missing inbound_tag or client_name")

    try:
        removed = singbox.remove_user_from_inbound(inbound_tag, client_name)
        if removed:
            await singbox.reload()
        return {"success": True, "removed": removed}
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
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    def _signed(self, payload: dict, secret: str) -> dict:
        return make_signed_request(payload, secret)

    async def ping_node(self, node_url: str, secret: str) -> bool:
        client = await self._client()
        payload = self._signed({"from": _local_peer_id()}, secret)
        try:
            resp = await client.post(
                f"{node_url.rstrip('/')}/federation/ping", json=payload, timeout=10
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def get_remote_inbounds(self, node_url: str, secret: str) -> List[Dict]:
        client = await self._client()
        payload = self._signed({"from": _local_peer_id()}, secret)
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
            "from": _local_peer_id(),
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
        self, node_url: str, secret: str, outbound: dict, auth_user: Optional[str] = None
    ) -> dict:
        client = await self._client()
        body: dict = {"from": _local_peer_id(), "outbound": outbound}
        if auth_user:
            body["auth_user"] = auth_user
        payload = self._signed(body, secret)
        resp = await client.post(
            f"{node_url.rstrip('/')}/federation/add_outbound", json=payload
        )
        if resp.status_code != 200:
            raise ValueError(f"Add outbound failed on {node_url}: {resp.text}")
        return resp.json()

    async def remove_link_from_node(
        self, node_url: str, secret: str, outbound_tag: str, auth_user: Optional[str] = None
    ) -> None:
        client = await self._client()
        body: dict = {
            "from": _local_peer_id(),
            "outbound_tag": outbound_tag,
        }
        if auth_user:
            body["auth_user"] = auth_user
        payload = self._signed(body, secret)
        resp = await client.post(
            f"{node_url.rstrip('/')}/federation/remove_link", json=payload
        )
        if resp.status_code != 200:
            raise ValueError(f"Remove link failed on {node_url}: {resp.text}")

    async def revoke_client(
        self, node_url: str, secret: str, inbound_tag: str, client_name: str
    ) -> None:
        client = await self._client()
        payload = self._signed(
            {
                "from": _local_peer_id(),
                "inbound_tag": inbound_tag,
                "client_name": client_name,
            },
            secret,
        )
        resp = await client.post(
            f"{node_url.rstrip('/')}/federation/revoke_client", json=payload
        )
        if resp.status_code != 200:
            raise ValueError(f"Revoke client failed on {node_url}: {resp.text}")

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
        """
        if len(node_chain) < 1:
            raise ValueError("Bridge requires at least 1 node")

        created = []
        local_outbounds: List[str] = []
        remote_links: List[Dict[str, str]] = []
        provisioned_clients: List[Dict[str, str]] = []
        local_id = _local_peer_id()

        try:
            first_node = node_chain[0]
            first_client_name = _bridge_client_name(local_id, node_chain, 0, first_node["name"])
            first_provision = await self.provision_client(
                first_node["url"],
                first_node["secret"],
                first_client_name,
            )
            provisioned_clients.append({
                "url": first_node["url"],
                "secret": first_node["secret"],
                "inbound_tag": first_provision["inbound_tag"],
                "client_name": first_provision["client_name"],
            })

            entry_outbound = _entry_outbound_tag(node_chain)
            outbound = build_outbound_from_provision(first_provision, tag=entry_outbound)
            singbox.save_outbound(outbound)
            await singbox.reload()
            local_outbounds.append(entry_outbound)
            created.append({"server": "local", "outbound_tag": entry_outbound})

            current_link = first_provision
            for hop_index in range(len(node_chain) - 1):
                current = node_chain[hop_index]
                next_node = node_chain[hop_index + 1]
                next_client_name = _bridge_client_name(
                    local_id, node_chain, hop_index + 1, next_node["name"]
                )
                next_provision = await self.provision_client(
                    next_node["url"],
                    next_node["secret"],
                    next_client_name,
                )
                provisioned_clients.append({
                    "url": next_node["url"],
                    "secret": next_node["secret"],
                    "inbound_tag": next_provision["inbound_tag"],
                    "client_name": next_provision["client_name"],
                })

                remote_outbound_tag = _bridge_outbound_tag(next_node["name"])
                remote_outbound = build_outbound_from_provision(
                    next_provision,
                    tag=remote_outbound_tag,
                )
                await self.add_outbound_to_node(
                    current["url"],
                    current["secret"],
                    remote_outbound,
                    auth_user=current_link["client_name"],
                )
                remote_links.append({
                    "url": current["url"],
                    "secret": current["secret"],
                    "outbound_tag": remote_outbound_tag,
                    "auth_user": current_link["client_name"],
                })
                created.append({
                    "server": current["name"],
                    "outbound_tag": remote_outbound_tag,
                    "auth_user": current_link["client_name"],
                })
                current_link = next_provision

            chain = " → ".join(["(this server)"] + [n["name"] for n in node_chain] + ["Internet"])
            return {
                "created": created,
                "chain": chain,
                "entry_outbound": entry_outbound,
            }
        except Exception as e:
            remote_cleanup_errors = []
            provision_cleanup_errors = []
            local_changed = False

            for tag in reversed(local_outbounds):
                local_changed = singbox.delete_outbound(tag) or local_changed
            if local_changed:
                try:
                    await singbox.reload()
                except Exception:
                    pass

            for link in reversed(remote_links):
                try:
                    await self.remove_link_from_node(
                        link["url"],
                        link["secret"],
                        link["outbound_tag"],
                        link["auth_user"],
                    )
                except Exception as cleanup_error:
                    remote_cleanup_errors.append(str(cleanup_error))

            for provision in reversed(provisioned_clients):
                try:
                    await self.revoke_client(
                        provision["url"],
                        provision["secret"],
                        provision["inbound_tag"],
                        provision["client_name"],
                    )
                except Exception as cleanup_error:
                    provision_cleanup_errors.append(str(cleanup_error))

            if remote_cleanup_errors or provision_cleanup_errors:
                cleanup_summary = "; ".join(remote_cleanup_errors + provision_cleanup_errors)
                raise ValueError(
                    f"Bridge creation failed: {e}. Cleanup was partial: {cleanup_summary}"
                )
            raise


fed_client = FederationClient()
