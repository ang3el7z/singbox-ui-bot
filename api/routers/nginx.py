import io
import zipfile
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from api.services import nginx_service
from api.deps import require_any_auth, audit

router = APIRouter()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("/status")
async def nginx_status(auth: dict = Depends(require_any_auth)):
    override = nginx_service.override_status()
    paths = nginx_service.get_hidden_paths()
    site_enabled = nginx_service.get_site_enabled()
    return {"override": override, "paths": paths, "site_enabled": site_enabled}


@router.post("/configure")
async def nginx_configure(auth: dict = Depends(require_any_auth)):
    from api.routers.settings_router import get_runtime
    nginx_service.ensure_htpasswd()
    config_text = nginx_service.generate_config(domain=get_runtime("domain"))
    nginx_service.write_config(config_text)
    ok, msg = await nginx_service.test_nginx_config()
    if not ok:
        raise HTTPException(status_code=500, detail=f"Config error: {msg}")
    ok, msg = await nginx_service.reload_nginx()
    await audit(auth["actor"], "nginx_configure")
    return {"success": ok, "message": msg}


class SslRequest(BaseModel):
    email: str = ""   # optional: if empty, auto-generated as admin@{domain}


@router.post("/ssl")
async def nginx_ssl(body: SslRequest = SslRequest(), auth: dict = Depends(require_any_auth)):
    from api.routers.settings_router import get_runtime
    domain = get_runtime("domain")
    if not domain:
        raise HTTPException(status_code=400, detail="Domain not configured. Set it in Settings first.")
    ok, output = await nginx_service.issue_ssl_cert(domain, email=body.email or None)
    await audit(auth["actor"], "nginx_ssl", f"domain={domain} email={body.email or 'auto'}")
    if not ok:
        raise HTTPException(status_code=500, detail=output)
    return {"success": True}


@router.get("/paths")
async def nginx_paths(auth: dict = Depends(require_any_auth)):
    return nginx_service.get_hidden_paths()


@router.get("/logs")
async def nginx_logs(lines: int = 50, auth: dict = Depends(require_any_auth)):
    logs = await nginx_service.get_access_logs(lines)
    return {"logs": logs}


@router.post("/override/upload")
async def upload_override(
    file: UploadFile = File(...),
    auth: dict = Depends(require_any_auth),
):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    filename = file.filename or ""
    if filename.lower().endswith((".html", ".htm")):
        nginx_service.save_override_html(content)
        await audit(auth["actor"], "nginx_override_html", filename)
        await nginx_service.reload_nginx()
        return {"detail": "HTML saved", "type": "html"}
    elif filename.lower().endswith(".zip"):
        count = nginx_service.save_override_zip(content)
        if not (nginx_service.OVERRIDE_DIR / "index.html").exists():
            nginx_service.remove_override()
            raise HTTPException(status_code=400, detail="index.html not found in ZIP")
        await audit(auth["actor"], "nginx_override_zip", f"{filename} ({count} files)")
        await nginx_service.reload_nginx()
        return {"detail": "ZIP extracted", "files": count, "type": "zip"}
    else:
        raise HTTPException(status_code=400, detail="Upload .html or .zip file")


@router.delete("/override")
async def delete_override(auth: dict = Depends(require_any_auth)):
    nginx_service.remove_override()
    await nginx_service.reload_nginx()
    await audit(auth["actor"], "nginx_override_delete")
    return {"detail": "Override removed, auth popup restored"}


@router.get("/override/status")
async def override_status(auth: dict = Depends(require_any_auth)):
    return nginx_service.override_status()


@router.post("/site/toggle")
async def site_toggle(enabled: bool, auth: dict = Depends(require_any_auth)):
    """
    Enable or disable the public site.
    enabled=true  → root '/' serves the uploaded override (or falls back to 401 popup).
    enabled=false → root '/' always shows the 401 Basic Auth camouflage popup.
    Regenerates nginx config and reloads nginx automatically.
    """
    from api.routers.settings_router import get_runtime
    nginx_service.set_site_enabled(enabled)
    config_text = nginx_service.generate_config(domain=get_runtime("domain"), site_enabled=enabled)
    nginx_service.write_config(config_text)
    ok, msg = await nginx_service.test_nginx_config()
    if not ok:
        # Rollback
        nginx_service.set_site_enabled(not enabled)
        raise HTTPException(status_code=500, detail=f"Config error: {msg}")
    await nginx_service.reload_nginx()
    await audit(auth["actor"], "nginx_site_toggle", f"enabled={enabled}")
    return {"site_enabled": enabled}
