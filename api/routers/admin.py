"""
Admin management router — accessible only via internal token (bot) or web JWT.
Handles: TG admin list, audit log, backup.
"""
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.database import get_db, Admin, AuditLog
from api.services.backup_service import build_backup_zip
from api.deps import require_any_auth, audit

router = APIRouter()


class AdminCreate(BaseModel):
    telegram_id: int
    username: Optional[str] = None


@router.get("/admins")
async def list_admins(db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    result = await db.execute(select(Admin).order_by(Admin.created_at))
    admins = result.scalars().all()
    return [
        {"id": a.id, "telegram_id": a.telegram_id, "username": a.username, "created_at": a.created_at.isoformat()}
        for a in admins
    ]


@router.post("/admins", status_code=201)
async def add_admin(
    body: AdminCreate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    existing = await db.execute(select(Admin).where(Admin.telegram_id == body.telegram_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Admin already exists")
    admin = Admin(telegram_id=body.telegram_id, username=body.username)
    db.add(admin)
    await db.commit()
    await audit(auth["actor"], "add_admin", f"tg_id={body.telegram_id}")
    return {"detail": "Admin added", "telegram_id": body.telegram_id}


@router.delete("/admins/{telegram_id}")
async def delete_admin(
    telegram_id: int,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    result = await db.execute(select(Admin).where(Admin.telegram_id == telegram_id))
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    await db.delete(admin)
    await db.commit()
    await audit(auth["actor"], "delete_admin", f"tg_id={telegram_id}")
    return {"detail": "Deleted"}


@router.get("/audit-log")
async def get_audit_log(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    result = await db.execute(
        select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": l.id, "actor": l.actor, "action": l.action,
            "details": l.details, "created_at": l.created_at.isoformat()
        }
        for l in logs
    ]


@router.get("/backup")
async def create_backup(auth: dict = Depends(require_any_auth)):
    """Create a recovery ZIP with secrets, config, DB, and related state."""
    buf = io.BytesIO(build_backup_zip())
    filename = f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
    await audit(auth["actor"], "create_backup")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
