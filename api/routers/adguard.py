from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List

from api.services.adguard_api import adguard, AdGuardAPIError
from api.deps import require_any_auth, audit

router = APIRouter()


class UpstreamBody(BaseModel):
    upstream: str


class FilterRuleBody(BaseModel):
    rule: str


class PasswordBody(BaseModel):
    password: str


@router.get("/status")
async def adguard_status(auth: dict = Depends(require_any_auth)):
    try:
        return await adguard.get_status()
    except AdGuardAPIError as e:
        return {"error": str(e), "available": False}


@router.get("/stats")
async def adguard_stats(auth: dict = Depends(require_any_auth)):
    try:
        return await adguard.get_stats()
    except AdGuardAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/protection")
async def toggle_protection(enabled: bool, auth: dict = Depends(require_any_auth)):
    await adguard.enable_protection(enabled)
    await audit(auth["actor"], "adguard_protection", f"enabled={enabled}")
    return {"detail": f"Protection {'enabled' if enabled else 'disabled'}"}


@router.get("/dns")
async def get_dns(auth: dict = Depends(require_any_auth)):
    return await adguard.get_dns_info()


@router.post("/dns/upstream")
async def add_upstream(body: UpstreamBody, auth: dict = Depends(require_any_auth)):
    info = await adguard.get_dns_info()
    upstreams = info.get("upstream_dns", [])
    if body.upstream not in upstreams:
        upstreams.append(body.upstream)
        await adguard.set_upstream_dns(upstreams)
    await audit(auth["actor"], "adguard_add_upstream", body.upstream)
    return {"detail": "Added", "upstreams": upstreams}


@router.delete("/dns/upstream")
async def delete_upstream(upstream: str, auth: dict = Depends(require_any_auth)):
    info = await adguard.get_dns_info()
    upstreams = [u for u in info.get("upstream_dns", []) if u != upstream]
    await adguard.set_upstream_dns(upstreams)
    await audit(auth["actor"], "adguard_del_upstream", upstream)
    return {"detail": "Deleted", "upstreams": upstreams}


@router.get("/rules")
async def get_rules(auth: dict = Depends(require_any_auth)):
    return {"rules": await adguard.get_user_rules()}


@router.post("/rules")
async def add_rule(body: FilterRuleBody, auth: dict = Depends(require_any_auth)):
    await adguard.add_filter_rule(body.rule)
    await audit(auth["actor"], "adguard_add_rule", body.rule)
    return {"detail": "Rule added"}


@router.delete("/rules")
async def delete_rule(rule: str, auth: dict = Depends(require_any_auth)):
    await adguard.remove_filter_rule(rule)
    await audit(auth["actor"], "adguard_del_rule", rule)
    return {"detail": "Rule deleted"}


@router.post("/password")
async def change_password(body: PasswordBody, auth: dict = Depends(require_any_auth)):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password too short")
    await adguard.change_password(body.password)
    await audit(auth["actor"], "adguard_change_password")
    return {"detail": "Password changed"}


@router.post("/sync-clients")
async def sync_clients(auth: dict = Depends(require_any_auth)):
    from api.database import async_session, Client
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(select(Client))
        sb_clients = result.scalars().all()

    ag_clients = await adguard.get_clients()
    ag_names = {c["name"] for c in ag_clients}
    added = 0
    for c in sb_clients:
        if c.name not in ag_names:
            await adguard.add_client({
                "name": c.name, "ids": [],
                "use_global_settings": True,
                "use_global_blocked_services": True,
                "filtering_enabled": True,
                "safebrowsing_enabled": True,
            })
            added += 1
    await audit(auth["actor"], "adguard_sync_clients", f"added={added}")
    return {"added": added}
