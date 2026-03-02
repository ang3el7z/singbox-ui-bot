import logging
import secrets
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.database import get_db, Client, ClientTemplate
from api.services.singbox import singbox, SingBoxError
from api.deps import require_any_auth, audit


async def _resolve_template(client: Client, db: AsyncSession) -> str:
    """Return the config_json for the client's assigned template, or the default."""
    if client.template_id:
        t = await db.get(ClientTemplate, client.template_id)
        if t:
            return t.config_json

    # Fall back to default template
    result = await db.execute(select(ClientTemplate).where(ClientTemplate.is_default == True))
    default = result.scalar_one_or_none()
    if default:
        return default.config_json

    # Last resort: seed data not yet loaded — return built-in tun JSON
    from api.services.template_seeds import get_builtin_config_json
    return get_builtin_config_json("tun")

router = APIRouter()

# ── Separate public router (no auth) ──────────────────────────────────────────
pub_router = APIRouter()


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
    template_id: Optional[int] = None   # None = use default template


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
        "template_id": c.template_id,   # None = using default template
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
    if "template_id" in body.model_fields_set:
        # Validate template exists if a non-None value is set
        if body.template_id is not None:
            t = await db.get(ClientTemplate, body.template_id)
            if not t:
                raise HTTPException(status_code=404, detail=f"Template id={body.template_id} not found")
        c.template_id = body.template_id

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


@pub_router.get("/sub/{sub_id}/windows.zip", response_class=None)
async def windows_zip(
    sub_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return a ready-to-use Windows Service ZIP for this client.

    Contains: sing-box.exe, winsw3.exe, winsw3.xml (with subscription URL),
              install/start/stop/restart/status/uninstall .cmd scripts.

    On first call, sing-box.exe and winsw3.exe are downloaded from GitHub
    Releases and cached in data/windows-service/.
    Subsequent calls serve instantly from cache.
    """
    from fastapi.responses import Response as FastAPIResponse
    result = await db.execute(select(Client).where(Client.sub_id == sub_id))
    c = result.scalar_one_or_none()
    if not c or not c.enable:
        raise HTTPException(status_code=404, detail="Subscription not found or disabled")

    from api.services.nginx_service import get_hidden_paths
    paths = get_hidden_paths()
    sub_url = f"{paths['subscriptions'].rstrip('/')}/{sub_id}"

    from api.services import windows_service as ws
    try:
        if not ws.binaries_ready():
            await ws.ensure_binaries()
        zip_bytes = ws.build_zip(sub_url, c.name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Windows zip error: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to build archive: {e}")

    return FastAPIResponse(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="singbox-windows.zip"'},
    )


@pub_router.get("/sub/{sub_id}/winsw.xml", response_class=None)
async def winsw_xml(
    sub_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return a WinSW v3 XML for installing sing-box as a Windows Service.
    The XML includes a <download> directive that fetches the subscription config
    from this server on every service start — keeping config always up to date.

    Usage:
      1. Download sing-box.exe from https://github.com/SagerNet/sing-box/releases
      2. Download WinSW-x64.exe from https://github.com/winsw/winsw/releases
      3. Rename WinSW-x64.exe → singbox-service.exe
      4. Download this XML → save as singbox-service.xml (same folder)
      5. Run as Administrator: singbox-service.exe install
      6. sc start singbox
    """
    from fastapi.responses import Response
    result = await db.execute(select(Client).where(Client.sub_id == sub_id))
    c = result.scalar_one_or_none()
    if not c or not c.enable:
        raise HTTPException(status_code=404, detail="Subscription not found or disabled")

    from api.services.nginx_service import get_hidden_paths
    paths = get_hidden_paths()
    sub_base = paths["subscriptions"].rstrip("/")
    sub_url = f"{sub_base}/{sub_id}"

    xml = f"""<service>
    <id>singbox</id>
    <name>Sing-Box VPN ({c.name})</name>
    <description>Sing-Box VPN client — managed by singbox-ui-bot</description>
    <executable>%BASE%\\sing-box.exe</executable>
    <arguments>run -c %BASE%\\config.json</arguments>
    <logmode>rotate</logmode>
    <onfailure action="restart" delay="10 sec" />
    <onfailure action="restart" delay="20 sec" />
    <onfailure action="restart" delay="30 sec" />
    <onfailure action="none" />
    <download from="{sub_url}" to="%BASE%\\config.json" failOnError="true" />
</service>"""

    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="singbox-service.xml"'},
    )


@pub_router.get("/sub/{sub_id}")
async def public_subscription(
    sub_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Public subscription endpoint — no auth required.
    Access via: https://domain/{hash}/sub/{sub_id}

    Uses the template assigned to the client, or the default template if none is set.
    Response includes Profile-* headers for sing-box / clash meta clients.
    """
    result = await db.execute(select(Client).where(Client.sub_id == sub_id))
    c = result.scalar_one_or_none()
    if not c or not c.enable:
        raise HTTPException(status_code=404, detail="Subscription not found or disabled")

    inbound = singbox.get_inbound(c.inbound_tag)
    if not inbound:
        raise HTTPException(status_code=404, detail="Inbound not found")

    template_json = await _resolve_template(c, db)
    client_dict = {"uuid": c.uuid, "password": c.password, "name": c.name}
    config = singbox.build_client_config(client_dict, inbound, template_json, sub_id=c.sub_id)

    return JSONResponse(
        content=config,
        headers={
            "Content-Disposition": f'attachment; filename="{c.name}.json"',
            "Profile-Title": c.name,
            "Profile-Update-Interval": "24",
            "Subscription-Userinfo": (
                f"upload={c.upload or 0}; download={c.download or 0}; "
                f"total={int((c.total_gb or 0) * 1024 ** 3)}; "
                f"expire={int(c.expiry_time / 1000) if c.expiry_time else 0}"
            ),
        },
    )


@router.get("/templates")
async def list_templates(auth: dict = Depends(require_any_auth)):
    """Return available client config templates."""
    return [
        {"id": tid, **meta}
        for tid, meta in singbox.CLIENT_TEMPLATES.items()
    ]


@router.get("/{client_id}/sub-url")
async def get_sub_url(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    """Return the public subscription URL(s) for a client."""
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    from api.services.nginx_service import get_hidden_paths
    paths = get_hidden_paths()
    sub_base = paths["subscriptions"].rstrip("/")  # https://domain/{hash}/sub
    sub_url = f"{sub_base}/{c.sub_id}"
    return {
        "sub_id":      c.sub_id,
        "url":         sub_url,
        "winsw_url":   f"{sub_url}/winsw.xml",
        "windows_zip": f"{sub_url}/windows.zip",
        "template_id": c.template_id,
    }


@router.get("/{client_id}/subscription")
async def get_subscription(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    """Return client-side sing-box config using the client's assigned template (or default)."""
    c = await db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    inbound = singbox.get_inbound(c.inbound_tag)
    if not inbound:
        raise HTTPException(status_code=404, detail="Inbound not found")
    template_json = await _resolve_template(c, db)
    client_dict = {"uuid": c.uuid, "password": c.password, "name": c.name}
    return singbox.build_client_config(client_dict, inbound, template_json, sub_id=c.sub_id)
