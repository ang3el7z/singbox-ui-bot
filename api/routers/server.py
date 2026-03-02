from fastapi import APIRouter, Depends
from api.services.singbox import singbox, SingBoxError
from api.deps import require_any_auth, audit

router = APIRouter()


@router.get("/status")
async def server_status(auth: dict = Depends(require_any_auth)):
    try:
        status = await singbox.get_status()
        return status
    except SingBoxError as e:
        return {"running": False, "error": str(e)}


@router.get("/logs")
async def server_logs(lines: int = 100, auth: dict = Depends(require_any_auth)):
    logs = await singbox.get_logs(lines)
    return {"logs": logs}


@router.post("/restart")
async def server_restart(auth: dict = Depends(require_any_auth)):
    ok = await singbox.restart()
    await audit(auth["actor"], "restart_singbox")
    return {"success": ok}


@router.post("/reload")
async def server_reload(auth: dict = Depends(require_any_auth)):
    ok = await singbox.reload()
    await audit(auth["actor"], "reload_singbox")
    return {"success": ok}


@router.get("/config")
async def get_raw_config(auth: dict = Depends(require_any_auth)):
    try:
        cfg = singbox.read_config()
        return cfg
    except SingBoxError as e:
        return {"error": str(e)}


@router.get("/keypair")
async def generate_keypair(auth: dict = Depends(require_any_auth)):
    return await singbox.generate_reality_keypair()
