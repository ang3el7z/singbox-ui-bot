import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.services.singbox import singbox, SingBoxError
from api.deps import require_any_auth, audit

router = APIRouter()

# Note: geosite/geoip are Xray concepts — not supported in sing-box.
# For geo-based filtering use rule_set pointing to an .srs file.
RuleKey = Literal["domain", "domain_suffix", "domain_keyword", "ip_cidr", "rule_set"]

_BUILTIN_OUTBOUNDS = ["proxy", "direct", "block", "dns"]


class RuleCreate(BaseModel):
    rule_key: RuleKey
    value: str   # comma-separated for domain/domain_suffix/domain_keyword/ip_cidr
    outbound: str = "proxy"  # any valid outbound tag, including federation nodes


class RuleSetCreate(BaseModel):
    tag: str
    url: str
    format: Literal["binary", "source"] = "binary"
    download_detour: str = "direct"   # "direct" or "proxy" (use proxy if GitHub is blocked)
    update_interval: str = "1d"       # "1h","6h","12h","1d","7d","30d"


@router.get("/outbounds")
async def list_outbounds(auth: dict = Depends(require_any_auth)):
    """Return all available outbound tags: built-ins + any federation/custom outbounds in config."""
    tags: list[str] = list(_BUILTIN_OUTBOUNDS)
    try:
        for ob in singbox.get_outbounds():
            tag = ob.get("tag", "")
            if tag and tag not in tags:
                tags.append(tag)
    except Exception:
        pass
    return {"outbounds": tags}


@router.get("/")
async def get_route(auth: dict = Depends(require_any_auth)):
    return singbox.get_route()


@router.get("/rules/{rule_key}")
async def list_rules(rule_key: str, auth: dict = Depends(require_any_auth)):
    pairs = singbox.get_route_rules(rule_key)
    return [{"value": v, "outbound": o} for v, o in pairs]


@router.post("/rules")
async def add_rule(body: RuleCreate, auth: dict = Depends(require_any_auth)):
    try:
        singbox.add_route_rule(body.rule_key, body.value, body.outbound)
        await singbox.reload()
    except SingBoxError as e:
        raise HTTPException(status_code=500, detail=str(e))
    await audit(auth["actor"], "add_route_rule", f"{body.rule_key}={body.value} → {body.outbound}")
    return {"detail": "Rule added"}


@router.delete("/rules")
async def delete_rule(rule_key: str, value: str, auth: dict = Depends(require_any_auth)):
    ok = singbox.remove_route_rule(rule_key, value)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    await singbox.reload()
    await audit(auth["actor"], "delete_route_rule", f"{rule_key}={value}")
    return {"detail": "Rule deleted"}


@router.post("/rule-sets")
async def add_rule_set(body: RuleSetCreate, auth: dict = Depends(require_any_auth)):
    try:
        cfg = singbox.read_config()
        route = cfg.setdefault("route", {})
        rule_sets = route.setdefault("rule_set", [])
        if any(rs["tag"] == body.tag for rs in rule_sets):
            raise HTTPException(status_code=400, detail="Rule set tag already exists")
        rule_sets.append({
            "tag": body.tag,
            "type": "remote",
            "format": body.format,
            "url": body.url,
            "download_detour": body.download_detour,
            "update_interval": body.update_interval,
        })
        singbox.write_config(cfg)
        await singbox.reload()
    except SingBoxError as e:
        raise HTTPException(status_code=500, detail=str(e))
    await audit(auth["actor"], "add_rule_set", f"tag={body.tag} url={body.url}")
    return {"detail": "Rule set added"}


@router.delete("/rule-sets/{tag}")
async def delete_rule_set(tag: str, auth: dict = Depends(require_any_auth)):
    cfg = singbox.read_config()
    route = cfg.get("route", {})
    rule_sets = route.get("rule_set", [])
    new_rs = [rs for rs in rule_sets if rs["tag"] != tag]
    if len(new_rs) == len(rule_sets):
        raise HTTPException(status_code=404, detail="Rule set not found")
    route["rule_set"] = new_rs
    # Also remove references in rules
    for rule in route.get("rules", []):
        if "rule_set" in rule and tag in rule["rule_set"]:
            rule["rule_set"].remove(tag)
    singbox.write_config(cfg)
    await singbox.reload()
    await audit(auth["actor"], "delete_rule_set", f"tag={tag}")
    return {"detail": "Rule set deleted"}


@router.get("/export")
async def export_rules(auth: dict = Depends(require_any_auth)):
    route = singbox.get_route()
    return {"rules": route.get("rules", []), "rule_set": route.get("rule_set", [])}


@router.post("/import")
async def import_rules(data: dict, auth: dict = Depends(require_any_auth)):
    cfg = singbox.read_config()
    route = cfg.setdefault("route", {})

    if "rules" in data:
        existing = route.setdefault("rules", [])
        existing.extend(data["rules"])
    if "rule_set" in data:
        existing_rs = route.setdefault("rule_set", [])
        existing_tags = {rs["tag"] for rs in existing_rs}
        for rs in data["rule_set"]:
            if rs.get("tag") not in existing_tags:
                existing_rs.append(rs)

    singbox.write_config(cfg)
    await singbox.reload()
    await audit(auth["actor"], "import_rules")
    return {"detail": "Rules imported"}
