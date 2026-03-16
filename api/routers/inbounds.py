import json
import secrets
from copy import deepcopy
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import Client, Inbound, get_db
from api.deps import audit, require_any_auth
from api.services.singbox import SingBoxError, singbox

router = APIRouter()

PROTOCOL_TEMPLATES = {
    # VLESS + Reality (recommended — camouflages as real HTTPS traffic)
    # Sing-box listens directly on the port, no Nginx proxy needed.
    "vless_reality": {
        "type": "vless",
        "listen": "0.0.0.0",
        "users": [],
        "tls": {
            "enabled": True,
            "server_name": "www.microsoft.com",
            "reality": {
                "enabled": True,
                "handshake": {"server": "www.microsoft.com", "server_port": 443},
                "private_key": "",
                "public_key": "",
                "short_id": [""],
            },
        },
        "multiplex": {"enabled": True, "padding": True},
        # subscribe_port / subscribe_tls are NOT set here:
        # client connects directly to listen_port with Reality TLS.
    },

    # VLESS + WebSocket, fronted by Nginx (Nginx does TLS on 443, proxies to this port)
    # subscribe_port=443: client connects to domain:443 via Nginx, NOT to listen_port directly.
    # subscribe_tls=True: Nginx terminates TLS, so client outbound needs TLS.
    "vless_ws": {
        "type": "vless",
        "listen": "0.0.0.0",
        "users": [],
        "transport": {"type": "ws", "path": "/vless"},
        "subscribe_port": 443,
        "subscribe_tls": True,
    },

    # VMess + WebSocket, fronted by Nginx (same pattern as vless_ws)
    "vmess_ws": {
        "type": "vmess",
        "listen": "0.0.0.0",
        "users": [],
        "transport": {"type": "ws", "path": "/vmess"},
        "subscribe_port": 443,
        "subscribe_tls": True,
    },

    # Shadowsocks (direct, no Nginx)
    "shadowsocks": {
        "type": "shadowsocks",
        "listen": "0.0.0.0",
        "method": "aes-256-gcm",
        "password": "",
        "users": [],
        "multiplex": {"enabled": True},
    },

    # Trojan + WebSocket, fronted by Nginx
    "trojan": {
        "type": "trojan",
        "listen": "0.0.0.0",
        "users": [],
        "transport": {"type": "ws", "path": "/trojan"},
        "subscribe_port": 443,
        "subscribe_tls": True,
    },

    # Hysteria2 (direct, own TLS — listens on UDP port)
    "hysteria2": {
        "type": "hysteria2",
        "listen": "0.0.0.0",
        "users": [],
        "tls": {"enabled": True},
        "up_mbps": 100,
        "down_mbps": 100,
    },

    # TUIC (direct, own TLS — listens on UDP port)
    "tuic": {
        "type": "tuic",
        "listen": "0.0.0.0",
        "users": [],
        "tls": {"enabled": True},
        "congestion_control": "bbr",
    },
}


class InboundCreate(BaseModel):
    tag: str
    protocol: str       # key from PROTOCOL_TEMPLATES
    listen_port: int
    custom_config: Optional[dict] = None  # override template fields


def _deep_merge(target: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


async def _load_inbound_with_meta(tag: str, db: AsyncSession) -> Optional[dict]:
    result = await db.execute(select(Inbound).where(Inbound.tag == tag))
    row = result.scalar_one_or_none()
    if row and row.config_json:
        return json.loads(row.config_json)
    return singbox.get_inbound(tag)


def _format(ib: Inbound) -> dict:
    return {
        "id": ib.id,
        "tag": ib.tag,
        "protocol": ib.protocol,
        "listen_port": ib.listen_port,
        "enable": ib.enable,
        "config": json.loads(ib.config_json),
        "created_at": ib.created_at.isoformat() if ib.created_at else None,
    }


@router.get("/")
async def list_inbounds(db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    # Return from live config (source of truth)
    inbounds = singbox.get_inbounds()
    return inbounds


@router.post("/", status_code=201)
async def create_inbound(
    body: InboundCreate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    if body.protocol not in PROTOCOL_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Unknown protocol: {body.protocol}. Choose from {list(PROTOCOL_TEMPLATES)}")

    template = deepcopy(PROTOCOL_TEMPLATES[body.protocol])
    if body.custom_config:
        _deep_merge(template, body.custom_config)

    template["tag"] = body.tag
    template["listen_port"] = body.listen_port

    # For Reality, auto-generate keypair
    if body.protocol == "vless_reality":
        kp = await singbox.generate_reality_keypair()
        short_id = await singbox.generate_short_id()
        if kp.get("private_key"):
            template["tls"]["reality"]["private_key"] = kp["private_key"]
            template["tls"]["reality"]["public_key"] = kp.get("public_key", "")
            template["tls"]["reality"]["short_id"] = [short_id]

    # For SS, auto-generate password
    if body.protocol == "shadowsocks" and not template.get("password"):
        template["password"] = secrets.token_hex(16)

    try:
        singbox.save_inbound(template)
        await singbox.reload()
    except SingBoxError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Mirror in DB for metadata
    ib = Inbound(
        tag=body.tag,
        protocol=body.protocol,
        listen_port=body.listen_port,
        enable=True,
        config_json=json.dumps(template),
    )
    db.add(ib)
    await db.commit()
    await audit(auth["actor"], "create_inbound", f"tag={body.tag} proto={body.protocol} port={body.listen_port}")
    return template


@router.get("/{tag}")
async def get_inbound(
    tag: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    ib = await _load_inbound_with_meta(tag, db)
    if not ib:
        raise HTTPException(status_code=404, detail="Inbound not found")
    return ib


@router.patch("/{tag}")
async def update_inbound(
    tag: str,
    update: dict,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    ib = await _load_inbound_with_meta(tag, db)
    if not ib:
        raise HTTPException(status_code=404, detail="Inbound not found")
    _deep_merge(ib, update)
    ib["tag"] = tag  # ensure tag not overwritten
    try:
        singbox.save_inbound(ib)
        await singbox.reload()
    except SingBoxError as e:
        raise HTTPException(status_code=500, detail=str(e))

    result = await db.execute(select(Inbound).where(Inbound.tag == tag))
    row = result.scalar_one_or_none()
    if row is None:
        row = Inbound(
            tag=tag,
            protocol=ib.get("type", "unknown"),
            listen_port=int(ib.get("listen_port", 0)),
            enable=bool(ib.get("enable", True)),
            config_json=json.dumps(ib),
        )
    else:
        row.protocol = ib.get("type", row.protocol)
        row.listen_port = int(ib.get("listen_port", row.listen_port))
        row.enable = bool(ib.get("enable", row.enable))
        row.config_json = json.dumps(ib)
    db.add(row)
    await db.commit()

    await audit(auth["actor"], "update_inbound", f"tag={tag}")
    return ib


@router.delete("/{tag}")
async def delete_inbound(
    tag: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    ok = singbox.delete_inbound(tag)
    if not ok:
        raise HTTPException(status_code=404, detail="Inbound not found")
    await singbox.reload()

    result = await db.execute(select(Inbound).where(Inbound.tag == tag))
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)

    result = await db.execute(select(Client).where(Client.inbound_tag == tag))
    deleted_clients = 0
    for client in result.scalars().all():
        await db.delete(client)
        deleted_clients += 1
    await db.commit()

    await audit(auth["actor"], "delete_inbound", f"tag={tag} deleted_clients={deleted_clients}")
    return {"detail": "Deleted", "deleted_clients": deleted_clients}
