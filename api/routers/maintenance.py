"""
Maintenance router — backup, log management, IP ban.
"""
import asyncio
import io
import ipaddress
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import require_any_auth, audit
from api.services import ip_ban as ip_ban_svc
from api.services import nginx_service
from api.services import update_service
from api.services.singbox import singbox
from api.services.warp_service import warp_service, WarpServiceError
from api.services.backup_service import (
    RestoreError,
    create_backup_file,
    schedule_restore_job,
)
from api.routers.settings_router import get_setting, set_setting

router = APIRouter()

BASE_DIR = Path(__file__).parent.parent.parent
LOGS_DIR = BASE_DIR / "nginx" / "logs"


# ─── Models ───────────────────────────────────────────────────────────────────

class IpBanAddBody(BaseModel):
    ip: str
    reason: Optional[str] = "manual"


class IntervalBody(BaseModel):
    hours: int   # 0 = disabled


class UpdateRunBody(BaseModel):
    # Backward-compatible field: maps to target=custom ref=<branch>
    branch: Optional[str] = None
    target: str = "latest_tag"     # latest_tag | custom
    ref: Optional[str] = None
    with_backup: bool = True
    backup_path: Optional[str] = None


class ReinstallRunBody(BaseModel):
    clean: bool = True
    target: str = "current"        # current | latest_tag | custom
    ref: Optional[str] = None
    with_backup: bool = True
    backup_path: Optional[str] = None


class WarpKeyBody(BaseModel):
    license_key: str


# ─── Status / settings ────────────────────────────────────────────────────────

@router.get("/status")
async def maintenance_status(auth=Depends(require_any_auth)):
    backup_hours    = int(await get_setting("backup_auto_hours",   "0") or "0")
    clean_hours     = int(await get_setting("logs_clean_hours",    "0") or "0")
    backup_last     = int(await get_setting("backup_last_at",      "0") or "0")
    clean_last      = int(await get_setting("logs_clean_last_at",  "0") or "0")
    warp_enabled    = (await get_setting("warp_enabled", "0") or "0") == "1"
    warp_key        = (await get_setting("warp_license_key", "") or "").strip()
    warp_runtime    = await asyncio.to_thread(warp_service.get_status)

    def _next(last: int, hours: int) -> Optional[str]:
        if not hours:
            return None
        nxt = last + hours * 3600
        return datetime.fromtimestamp(nxt).strftime("%Y-%m-%d %H:%M") if nxt > time.time() else "soon"

    return {
        "backup": {
            "auto_hours":  backup_hours,
            "last_at":     datetime.fromtimestamp(backup_last).strftime("%Y-%m-%d %H:%M") if backup_last else None,
            "next_at":     _next(backup_last, backup_hours),
        },
        "logs": {
            "auto_clean_hours": clean_hours,
            "last_clean_at":    datetime.fromtimestamp(clean_last).strftime("%Y-%m-%d %H:%M") if clean_last else None,
            "next_clean_at":    _next(clean_last, clean_hours),
            "files":            _log_files_info(),
        },
        "ip_ban": {
            "count": len(ip_ban_svc.get_banned_list()),
        },
        "warp": {
            "enabled": warp_enabled,
            "key_set": bool(warp_key),
            "status": warp_runtime.get("warp", "off"),
            "service_running": bool(warp_runtime.get("service_running")),
            "container_running": bool(warp_runtime.get("running")),
        },
    }


# ─── Backup ───────────────────────────────────────────────────────────────────

# ─── WARP ────────────────────────────────────────────────────────────────────

def _mask_key(value: str) -> str:
    key = (value or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


async def _warp_payload() -> dict:
    enabled = (await get_setting("warp_enabled", "0") or "0") == "1"
    key = (await get_setting("warp_license_key", "") or "").strip()
    runtime = await asyncio.to_thread(warp_service.get_status)
    return {
        "enabled": enabled,
        "license_key_set": bool(key),
        "license_key_masked": _mask_key(key),
        "runtime": runtime,
    }


@router.get("/warp/status")
async def warp_status(auth=Depends(require_any_auth)):
    return await _warp_payload()


@router.post("/warp/on")
async def warp_on(auth=Depends(require_any_auth)):
    key = (await get_setting("warp_license_key", "") or "").strip() or None
    try:
        runtime = await asyncio.to_thread(warp_service.turn_on, key)
    except WarpServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    await set_setting("warp_enabled", "1")
    changed = singbox.ensure_builtin_outbound("warp")
    if changed:
        try:
            await singbox.reload()
        except Exception:
            pass
    await audit(auth["actor"], "warp_on")
    payload = await _warp_payload()
    payload["runtime"] = runtime
    return payload


@router.post("/warp/off")
async def warp_off(auth=Depends(require_any_auth)):
    try:
        runtime = await asyncio.to_thread(warp_service.turn_off, True)
    except WarpServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    await set_setting("warp_enabled", "0")
    await audit(auth["actor"], "warp_off")
    payload = await _warp_payload()
    payload["runtime"] = runtime
    return payload


@router.post("/warp/key")
async def warp_set_key(body: WarpKeyBody, auth=Depends(require_any_auth)):
    key = (body.license_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="license_key cannot be empty")
    if len(key) < 8:
        raise HTTPException(status_code=400, detail="license_key looks too short")

    await set_setting("warp_license_key", key)
    enabled = (await get_setting("warp_enabled", "0") or "0") == "1"
    applied = False

    if enabled:
        try:
            await asyncio.to_thread(warp_service.turn_on, key)
            applied = True
        except WarpServiceError as exc:
            raise HTTPException(status_code=500, detail=f"Key saved, but apply failed: {exc}")

    await audit(auth["actor"], "warp_set_key", "updated")
    payload = await _warp_payload()
    payload["applied_now"] = applied
    return payload


@router.delete("/warp/key")
async def warp_clear_key(auth=Depends(require_any_auth)):
    await set_setting("warp_license_key", "")
    enabled = (await get_setting("warp_enabled", "0") or "0") == "1"

    # Recreate registration without license if WARP is enabled,
    # otherwise just remove the current registration.
    try:
        await asyncio.to_thread(warp_service.turn_off, True)
        if enabled:
            await asyncio.to_thread(warp_service.turn_on, None)
    except WarpServiceError as exc:
        raise HTTPException(status_code=500, detail=f"Key cleared, but refresh failed: {exc}")

    await audit(auth["actor"], "warp_clear_key")
    payload = await _warp_payload()
    payload["applied_now"] = enabled
    return payload


@router.get("/backup/download")
async def backup_download(auth=Depends(require_any_auth)):
    """Create and stream a recovery ZIP."""
    backup_path = create_backup_file(prefix="preflight_backup")
    buf = io.BytesIO(backup_path.read_bytes())
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    await audit(auth["actor"], "backup_download")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="backup_{ts}.zip"',
            "X-Singbox-Backup-Path": str(backup_path),
        },
    )


@router.post("/backup/run")
async def backup_run_now(auth=Depends(require_any_auth)):
    """Trigger an immediate auto-backup (creates ZIP and sends to Telegram admins)."""
    from api.services.scheduler import run_backup_job
    ok = await run_backup_job()
    await audit(auth["actor"], "backup_run_now")
    return {"success": ok}


@router.post("/restore")
async def restore_from_backup(
    file: UploadFile = File(...),
    create_safety_backup: bool = True,
    auth=Depends(require_any_auth),
):
    filename = file.filename or "backup.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip recovery archive")

    content = await file.read()
    try:
        result = await schedule_restore_job(
            content,
            filename=filename,
            create_safety_backup=create_safety_backup,
        )
    except RestoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Restore scheduling failed: {exc}")

    await audit(
        auth["actor"],
        "maintenance_restore_scheduled",
        f"file={filename} safety_backup={create_safety_backup}",
    )
    return result


@router.post("/backup/settings")
async def backup_set_interval(body: IntervalBody, auth=Depends(require_any_auth)):
    if body.hours < 0:
        raise HTTPException(status_code=400, detail="hours must be >= 0")
    await set_setting("backup_auto_hours", str(body.hours))
    await audit(auth["actor"], "backup_interval_set", f"hours={body.hours}")
    return {"backup_auto_hours": body.hours}


# ─── Logs ─────────────────────────────────────────────────────────────────────

def _log_files_info() -> list[dict]:
    if not LOGS_DIR.exists():
        return []
    files = []
    for f in sorted(LOGS_DIR.glob("*.log")):
        size = f.stat().st_size
        files.append({"name": f.name, "size_bytes": size, "size_kb": round(size / 1024, 1)})
    return files


@router.get("/logs/list")
async def logs_list(auth=Depends(require_any_auth)):
    return {"files": _log_files_info()}


@router.get("/logs/download/{name}")
async def log_download(name: str, auth=Depends(require_any_auth)):
    """Download a specific log file."""
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = LOGS_DIR / name
    if not path.exists() or not path.suffix == ".log":
        raise HTTPException(status_code=404, detail="Log file not found")
    content = path.read_bytes()
    await audit(auth["actor"], "log_download", name)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/logs/clear/{name}")
async def log_clear_one(name: str, auth=Depends(require_any_auth)):
    """Truncate a specific log file."""
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = LOGS_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    path.write_bytes(b"")
    await audit(auth["actor"], "log_clear", name)
    return {"detail": f"{name} cleared"}


@router.post("/logs/clear-all")
async def log_clear_all(auth=Depends(require_any_auth)):
    """Truncate all log files."""
    cleared = []
    for f in LOGS_DIR.glob("*.log"):
        f.write_bytes(b"")
        cleared.append(f.name)
    await audit(auth["actor"], "log_clear_all")
    return {"cleared": cleared}


@router.post("/logs/settings")
async def log_set_auto_clean(body: IntervalBody, auth=Depends(require_any_auth)):
    if body.hours < 0:
        raise HTTPException(status_code=400, detail="hours must be >= 0")
    await set_setting("logs_clean_hours", str(body.hours))
    await audit(auth["actor"], "log_autoclean_set", f"hours={body.hours}")
    return {"logs_clean_hours": body.hours}


# ─── IP Ban ───────────────────────────────────────────────────────────────────

@router.get("/ip-ban/list")
async def ip_ban_list(auth=Depends(require_any_auth)):
    return {"banned": ip_ban_svc.get_banned_list()}


@router.post("/ip-ban/add")
async def ip_ban_add(body: IpBanAddBody, auth=Depends(require_any_auth)):
    try:
        ip = str(ipaddress.ip_address(body.ip))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid IP address")
    ip_ban_svc.add_ip(ip, reason=body.reason or "manual")
    ok, msg = await ip_ban_svc.sync_to_nginx()
    await audit(auth["actor"], "ip_ban_add", f"ip={ip} reason={body.reason}")
    return {"ip": ip, "nginx_reloaded": ok}


@router.delete("/ip-ban/{ip}")
async def ip_ban_remove(ip: str, auth=Depends(require_any_auth)):
    if not ip_ban_svc.remove_ip(ip):
        raise HTTPException(status_code=404, detail="IP not in ban list")
    ok, _ = await ip_ban_svc.sync_to_nginx()
    await audit(auth["actor"], "ip_ban_remove", f"ip={ip}")
    return {"ip": ip, "nginx_reloaded": ok}


@router.post("/ip-ban/analyze")
async def ip_ban_analyze(threshold: int = 30, auth=Depends(require_any_auth)):
    """Scan nginx access.log for suspicious IPs. Does NOT ban them automatically."""
    suspicious = ip_ban_svc.analyze_logs(threshold=threshold)
    return {"suspicious": suspicious, "threshold": threshold}


@router.post("/ip-ban/ban-analyzed")
async def ip_ban_from_analyzed(threshold: int = 30, auth=Depends(require_any_auth)):
    """Ban all suspicious IPs found in logs at once."""
    suspicious = ip_ban_svc.analyze_logs(threshold=threshold)
    for entry in suspicious:
        ip_ban_svc.add_ip(entry["ip"], reason=entry["reason"], auto=True)
    if suspicious:
        await ip_ban_svc.sync_to_nginx()
    await audit(auth["actor"], "ip_ban_bulk", f"banned={len(suspicious)}")
    return {"banned": len(suspicious)}


@router.post("/ip-ban/clear-auto")
async def ip_ban_clear_auto(auth=Depends(require_any_auth)):
    """Remove all auto-added bans (keep manual ones)."""
    count = ip_ban_svc.clear_auto_banned()
    if count > 0:
        await ip_ban_svc.sync_to_nginx()
    await audit(auth["actor"], "ip_ban_clear_auto", f"removed={count}")
    return {"removed": count}


# ─── Windows Service binaries ──────────────────────────────────────────────────

@router.get("/windows/binaries-status")
async def windows_binaries_status(auth=Depends(require_any_auth)):
    """Check whether Windows Service binaries are cached."""
    from api.services.windows_service import binaries_ready, SINGBOX_EXE, WINSW_EXE, SINGBOX_VERSION
    return {
        "ready": binaries_ready(),
        "sing_box_cached": SINGBOX_EXE.exists(),
        "winsw_cached": WINSW_EXE.exists(),
        "sing_box_version": SINGBOX_VERSION,
        "cache_dir": str(SINGBOX_EXE.parent),
    }


@router.post("/windows/prefetch-binaries")
async def prefetch_windows_binaries(auth=Depends(require_any_auth)):
    """
    Download sing-box.exe (Windows AMD64) and winsw3.exe from GitHub Releases
    and cache them in data/windows-service/.

    After this, GET /api/sub/{sub_id}/windows.zip will work instantly.
    Takes 30–120 seconds depending on connection speed.
    """
    from api.services.windows_service import ensure_binaries, SINGBOX_VERSION
    try:
        await ensure_binaries()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")
    await audit(auth["actor"], "prefetch_windows_binaries", f"version={SINGBOX_VERSION}")
    return {"detail": "Binaries downloaded and cached successfully"}


# ─── Update (git + branch/tag + run update job) ──────────────────────────────

@router.get("/update/info")
async def update_info(refresh: bool = True, auth=Depends(require_any_auth)):
    try:
        git = await asyncio.to_thread(update_service.get_update_info, refresh)
        job = await asyncio.to_thread(update_service.get_update_status, 120)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"git": git, "job": job}


@router.get("/update/logs")
async def update_logs(lines: int = 200, auth=Depends(require_any_auth)):
    lines = max(20, min(lines, 1000))
    job = await asyncio.to_thread(update_service.get_update_status, lines)
    return job


@router.post("/update/run")
async def update_run(body: UpdateRunBody = UpdateRunBody(), auth=Depends(require_any_auth)):
    try:
        result = await asyncio.to_thread(
            update_service.start_update,
            actor=auth["actor"],
            backup_path=body.backup_path,
            target=body.target,
            ref=body.ref,
            with_backup=body.with_backup,
            branch=body.branch,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await audit(
        auth["actor"],
        "maintenance_update_run",
        f"target={result.get('target')} ref={result.get('target_ref')}",
    )
    return result


@router.post("/reinstall/run")
async def reinstall_run(body: ReinstallRunBody = ReinstallRunBody(), auth=Depends(require_any_auth)):
    try:
        result = await asyncio.to_thread(
            update_service.start_reinstall,
            actor=auth["actor"],
            clean=body.clean,
            backup_path=body.backup_path,
            with_backup=body.with_backup,
            target=body.target,
            ref=body.ref,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await audit(
        auth["actor"],
        "maintenance_reinstall_run",
        f"clean={body.clean} target={body.target} with_backup={body.with_backup}",
    )
    return result


@router.post("/update/cleanup")
async def update_cleanup(auth=Depends(require_any_auth)):
    try:
        result = await asyncio.to_thread(update_service.cleanup_update_job)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await audit(auth["actor"], "maintenance_update_cleanup")
    return result
