"""
Maintenance router — backup, log management, IP ban.
"""
import io
import ipaddress
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import require_any_auth, audit
from api.services import ip_ban as ip_ban_svc
from api.services import nginx_service
from api.services.backup_service import build_backup_zip
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


# ─── Status / settings ────────────────────────────────────────────────────────

@router.get("/status")
async def maintenance_status(auth=Depends(require_any_auth)):
    backup_hours    = int(await get_setting("backup_auto_hours",   "0") or "0")
    clean_hours     = int(await get_setting("logs_clean_hours",    "0") or "0")
    backup_last     = int(await get_setting("backup_last_at",      "0") or "0")
    clean_last      = int(await get_setting("logs_clean_last_at",  "0") or "0")

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
    }


# ─── Backup ───────────────────────────────────────────────────────────────────

@router.get("/backup/download")
async def backup_download(auth=Depends(require_any_auth)):
    """Create and stream a recovery ZIP."""
    buf = io.BytesIO(build_backup_zip())
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    await audit(auth["actor"], "backup_download")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="backup_{ts}.zip"'},
    )


@router.post("/backup/run")
async def backup_run_now(auth=Depends(require_any_auth)):
    """Trigger an immediate auto-backup (creates ZIP and sends to Telegram admins)."""
    from api.services.scheduler import run_backup_job
    ok = await run_backup_job()
    await audit(auth["actor"], "backup_run_now")
    return {"success": ok}


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
