import secrets
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.database import get_db, Client
from api.services.singbox import singbox, SingBoxError
from api.deps import require_any_auth, audit

router = APIRouter()


class ClientCreate(BaseModel):
    name: str
    inbound_tag: str
    total_gb: float = 0.0       # 0 = unlimited
    expire_days: int = 0        # 0 = no expiry
    tg_id: Optional[str] = None


class ClientUpdate(BaseModel):
    total_gb: Optional[float] = None
    expire_days: Optional[int] = None
    enable: Optional[bool] = None
    tg_id: Optional[str] = None


def _expiry_ms(days: int) -> Optional[int]:
    if days <= 0:
        return None
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return int(dt.timestamp() * 1000)


def _format_client(c: Client) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "inbound_tag": c.inbound_tag,
        "protocol": c.protocol,
        "uuid": c.uuid,
        "password": c.password,
        "sub_id": c.sub_id,
        "total_gb": c.total_gb,
        "expiry_time": c.expiry_time,
        "enable": c.enable,
        "upload": c.upload,
        "download": c.download,
        "tg_id": c.tg_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/")
async def list_clients(db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    result = await db.execute(select(Client).order_by(Client.created_at.desc()))
    clients = result.scalars().all()
    return [_format_client(c) for c in clients]


@router.get("/{client_id}")
async def get_client(client_id: int, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return _format_client(c)


@router.post("/", status_code=201)
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    # Determine protocol from inbound
    inbound = singbox.get_inbound(body.inbound_tag)
    if not inbound:
        raise HTTPException(status_code=404, detail=f"Inbound '{body.inbound_tag}' not found")

    proto = inbound.get("type", "vless")
    new_uuid = str(uuid_lib.uuid4())
    new_password = secrets.token_hex(16)
    sub_id = secrets.token_hex(8)

    # Credentials depend on protocol
    user_entry: dict = {"name": body.name}
    if proto in ("vless", "vmess", "tuic"):
        user_entry["uuid"] = new_uuid
    elif proto in ("trojan", "hysteria2", "shadowsocks"):
        user_entry["password"] = new_password
    elif proto == "shadowsocks":
        user_entry["password"] = new_password

    # Add to sing-box config
    try:
        singbox.add_user_to_inbound(body.inbound_tag, user_entry)
        await singbox.reload()
    except SingBoxError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Save metadata to DB
    client = Client(
        name=body.name,
        inbound_tag=body.inbound_tag,
        protocol=proto,
        uuid=new_uuid if proto in ("vless", "vmess", "tuic") else None,
        password=new_password if proto in ("trojan", "hysteria2", "shadowsocks") else None,
        sub_id=sub_id,
        total_gb=body.total_gb,
        expiry_time=_expiry_ms(body.expire_days),
        enable=True,
        tg_id=body.tg_id,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    await audit(auth["actor"], "create_client", f"name={body.name} inbound={body.inbound_tag}")
    return _format_client(client)


@router.patch("/{client_id}")
async def update_client(
    client_id: int,
    body: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")

    if body.total_gb is not None:
        c.total_gb = body.total_gb
    if body.expire_days is not None:
        c.expiry_time = _expiry_ms(body.expire_days)
    if body.enable is not None:
        c.enable = body.enable
        # toggle in config: remove/re-add user
        try:
            if body.enable:
                proto = c.protocol
                user_entry = {"name": c.name}
                if proto in ("vless", "vmess", "tuic"):
                    user_entry["uuid"] = c.uuid
                else:
                    user_entry["password"] = c.password
                singbox.add_user_to_inbound(c.inbound_tag, user_entry)
            else:
                singbox.remove_user_from_inbound(c.inbound_tag, c.name)
            await singbox.reload()
        except SingBoxError as e:
            raise HTTPException(status_code=500, detail=str(e))
    if body.tg_id is not None:
        c.tg_id = body.tg_id

    db.add(c)
    await db.commit()
    await audit(auth["actor"], "update_client", f"id={client_id}")
    return _format_client(c)


@router.delete("/{client_id}")
async def delete_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        singbox.remove_user_from_inbound(c.inbound_tag, c.name)
        await singbox.reload()
    except SingBoxError:
        pass  # proceed with DB delete even if config removal fails
    await db.delete(c)
    await db.commit()
    await audit(auth["actor"], "delete_client", f"id={client_id} name={c.name}")
    return {"detail": "Deleted"}


@router.post("/{client_id}/reset-stats")
async def reset_client_stats(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    c.upload = 0
    c.download = 0
    db.add(c)
    await db.commit()
    await audit(auth["actor"], "reset_client_stats", f"id={client_id}")
    return {"detail": "Stats reset"}


@router.get("/{client_id}/subscription")
async def get_subscription(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    """Return client-side config for this client."""
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    inbound = singbox.get_inbound(c.inbound_tag)
    if not inbound:
        raise HTTPException(status_code=404, detail="Inbound not found")
    client_dict = {"uuid": c.uuid, "password": c.password, "name": c.name}
    config = singbox.build_client_config(client_dict, inbound)
    return config
