"""
Client subscription templates — CRUD + set-default + assign to client.

A template stores a full sing-box client config JSON with a placeholder outbound:
  {"tag": "proxy", "type": "__proxy__"}
This placeholder is replaced at subscription time with the real proxy outbound
built from client credentials + inbound settings.

Endpoints:
  GET    /api/client-templates/presets    list built-in preset templates (not seeded)
  POST   /api/client-templates/presets/{name}/install  add a preset to the DB
  GET    /api/client-templates/           list all templates
  POST   /api/client-templates/           create new template
  GET    /api/client-templates/{id}       get single template
  PUT    /api/client-templates/{id}       update template
  DELETE /api/client-templates/{id}       delete template
  POST   /api/client-templates/{id}/set-default   mark as default
  GET    /api/client-templates/default    get current default template
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.database import get_db, ClientTemplate, Client
from api.deps import require_any_auth, audit

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class TemplateCreate(BaseModel):
    name: str
    label: str
    config_json: str   # JSON string; must contain {"type":"__proxy__"} outbound

    @field_validator("config_json")
    @classmethod
    def validate_json(cls, v: str) -> str:
        try:
            cfg = json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
        # Check placeholder exists
        outbounds = cfg.get("outbounds", [])
        if not any(ob.get("type") == "__proxy__" for ob in outbounds):
            raise ValueError(
                'config_json must contain at least one outbound with "type": "__proxy__" '
                'as the proxy placeholder.'
            )
        return v


class TemplateUpdate(BaseModel):
    label: str | None = None
    config_json: str | None = None

    @field_validator("config_json")
    @classmethod
    def validate_json(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            cfg = json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
        outbounds = cfg.get("outbounds", [])
        if not any(ob.get("type") == "__proxy__" for ob in outbounds):
            raise ValueError('config_json must contain an outbound with "type": "__proxy__".')
        return v


def _fmt(t: ClientTemplate) -> dict:
    return {
        "id":          t.id,
        "name":        t.name,
        "label":       t.label,
        "is_default":  t.is_default,
        "config_json": t.config_json,
        "created_at":  t.created_at.isoformat() if t.created_at else None,
        "updated_at":  t.updated_at.isoformat() if t.updated_at else None,
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/presets")
async def list_presets(auth: dict = Depends(require_any_auth)):
    """Return built-in preset templates that can be installed into the DB."""
    from api.services.template_seeds import PRESET_TEMPLATES
    return [{"name": t["name"], "label": t["label"]} for t in PRESET_TEMPLATES]


@router.post("/presets/{name}/install", status_code=201)
async def install_preset(
    name: str,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    """Add a preset template to the database (one-click install)."""
    from api.services.template_seeds import PRESET_TEMPLATES
    preset = next((t for t in PRESET_TEMPLATES if t["name"] == name), None)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
    existing = await db.execute(select(ClientTemplate).where(ClientTemplate.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Template '{name}' already installed")
    t = ClientTemplate(
        name=preset["name"],
        label=preset["label"],
        is_default=False,
        config_json=json.dumps(preset["config"], ensure_ascii=False),
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    await audit(auth["actor"], "install_preset_template", f"name={name}")
    return _fmt(t)


@router.get("/default")
async def get_default_template(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    result = await db.execute(select(ClientTemplate).where(ClientTemplate.is_default == True))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="No default template set")
    return _fmt(t)


@router.get("/")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    result = await db.execute(select(ClientTemplate).order_by(ClientTemplate.id))
    return [_fmt(t) for t in result.scalars().all()]


@router.post("/", status_code=201)
async def create_template(
    body: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    # Ensure unique name
    existing = await db.execute(select(ClientTemplate).where(ClientTemplate.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Template '{body.name}' already exists")

    t = ClientTemplate(name=body.name, label=body.label, config_json=body.config_json)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    await audit(auth["actor"], "create_template", f"name={body.name}")
    return _fmt(t)


@router.get("/{tid}")
async def get_template(
    tid: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    t = await db.get(ClientTemplate, tid)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return _fmt(t)


@router.put("/{tid}")
async def update_template(
    tid: int,
    body: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    t = await db.get(ClientTemplate, tid)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if body.label is not None:
        t.label = body.label
    if body.config_json is not None:
        t.config_json = body.config_json
    db.add(t)
    await db.commit()
    await audit(auth["actor"], "update_template", f"id={tid}")
    return _fmt(t)


@router.delete("/{tid}")
async def delete_template(
    tid: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    t = await db.get(ClientTemplate, tid)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if t.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default template. Set another as default first.")

    # Unassign from clients that use this template
    result = await db.execute(select(Client).where(Client.template_id == tid))
    for c in result.scalars().all():
        c.template_id = None
        db.add(c)

    await db.delete(t)
    await db.commit()
    await audit(auth["actor"], "delete_template", f"id={tid} name={t.name}")
    return {"detail": "Deleted"}


@router.post("/{tid}/set-default")
async def set_default(
    tid: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    t = await db.get(ClientTemplate, tid)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    # Clear current default
    result = await db.execute(select(ClientTemplate).where(ClientTemplate.is_default == True))
    for old in result.scalars().all():
        old.is_default = False
        db.add(old)

    t.is_default = True
    db.add(t)
    await db.commit()
    await audit(auth["actor"], "set_default_template", f"id={tid} name={t.name}")
    return _fmt(t)
