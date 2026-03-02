"""
Windows Service package builder.

Generates a ready-to-use ZIP archive for installing sing-box as a Windows Service
using WinSW (Windows Service Wrapper).

Archive contents:
  sing-box.exe        — sing-box Windows AMD64 binary
  winsw3.exe          — WinSW v3 service wrapper
  winsw3.xml          — WinSW config with subscription URL filled in
  install.cmd         — winsw3.exe install
  start.cmd           — winsw3.exe start
  stop.cmd            — winsw3.exe stop
  restart.cmd         — winsw3.exe stop + start
  status.cmd          — winsw3.exe status
  uninstall.cmd       — winsw3.exe uninstall

Binaries are downloaded from GitHub Releases on first use and cached in data/windows-service/.
"""
import io
import zipfile
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/windows-service")
SINGBOX_EXE = CACHE_DIR / "sing-box.exe"
WINSW_EXE   = CACHE_DIR / "winsw3.exe"

# Official download URLs — keep in sync with docker-compose.yml sing-box version
SINGBOX_VERSION = "1.11.0"
SINGBOX_ZIP_URL = (
    f"https://github.com/SagerNet/sing-box/releases/download/"
    f"v{SINGBOX_VERSION}/sing-box-{SINGBOX_VERSION}-windows-amd64.zip"
)
SINGBOX_EXE_IN_ZIP = f"sing-box-{SINGBOX_VERSION}-windows-amd64/sing-box.exe"

# WinSW v3 — latest stable alpha (used by vpnbot)
WINSW_URL = "https://github.com/winsw/winsw/releases/download/v3.0.0-alpha.11/WinSW-x64.exe"


# ─── CMD scripts (identical to vpnbot) ───────────────────────────────────────

_SCRIPTS: dict[str, str] = {
    "install.cmd":   "winsw3.exe install\r\npause\r\n",
    "start.cmd":     "winsw3.exe start\r\n",
    "stop.cmd":      "winsw3.exe stop\r\n",
    "restart.cmd":   "winsw3.exe stop\r\nwinsw3.exe start\r\n",
    "status.cmd":    "winsw3.exe status\r\npause\r\n",
    "uninstall.cmd": "winsw3.exe uninstall\r\npause\r\n",
}


def _winsw_xml(sub_url: str, client_name: str) -> str:
    return (
        f"<service>\r\n"
        f"    <id>singbox</id>\r\n"
        f"    <name>Sing-Box VPN ({client_name})</name>\r\n"
        f"    <description>Sing-Box VPN client — managed by singbox-ui-bot</description>\r\n"
        f"    <executable>%BASE%\\sing-box.exe</executable>\r\n"
        f"    <arguments>run -c %BASE%\\config.json</arguments>\r\n"
        f"    <logmode>rotate</logmode>\r\n"
        f"    <onfailure action=\"restart\" delay=\"10 sec\" />\r\n"
        f"    <onfailure action=\"restart\" delay=\"20 sec\" />\r\n"
        f"    <onfailure action=\"restart\" delay=\"30 sec\" />\r\n"
        f"    <onfailure action=\"none\" />\r\n"
        f"    <download from=\"{sub_url}\" to=\"%BASE%\\config.json\" failOnError=\"true\" />\r\n"
        f"</service>\r\n"
    )


# ─── Binary download ──────────────────────────────────────────────────────────

async def _download_file(url: str, dest: Path) -> None:
    """Download a file from URL to dest, following redirects."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)


async def _ensure_singbox_exe() -> None:
    """Download and extract sing-box.exe for Windows if not cached."""
    if SINGBOX_EXE.exists():
        return
    logger.info("Downloading sing-box.exe Windows binary...")
    zip_path = CACHE_DIR / "singbox-windows.zip"
    await _download_file(SINGBOX_ZIP_URL, zip_path)
    # Extract sing-box.exe from the nested zip
    with zipfile.ZipFile(zip_path) as zf:
        data = zf.read(SINGBOX_EXE_IN_ZIP)
    SINGBOX_EXE.write_bytes(data)
    zip_path.unlink(missing_ok=True)
    logger.info("sing-box.exe cached at %s", SINGBOX_EXE)


async def _ensure_winsw_exe() -> None:
    """Download WinSW v3 if not cached."""
    if WINSW_EXE.exists():
        return
    logger.info("Downloading winsw3.exe...")
    await _download_file(WINSW_URL, WINSW_EXE)
    logger.info("winsw3.exe cached at %s", WINSW_EXE)


async def ensure_binaries() -> None:
    """Ensure both binaries are cached. Downloads if missing."""
    await _ensure_singbox_exe()
    await _ensure_winsw_exe()


def binaries_ready() -> bool:
    return SINGBOX_EXE.exists() and WINSW_EXE.exists()


# ─── ZIP generation ───────────────────────────────────────────────────────────

def build_zip(sub_url: str, client_name: str) -> bytes:
    """
    Build the Windows Service ZIP archive in memory.
    Returns raw ZIP bytes.
    Raises FileNotFoundError if binaries are not yet downloaded.
    """
    if not SINGBOX_EXE.exists():
        raise FileNotFoundError("sing-box.exe not cached. Call /api/maintenance/prefetch-windows first.")
    if not WINSW_EXE.exists():
        raise FileNotFoundError("winsw3.exe not cached. Call /api/maintenance/prefetch-windows first.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Binaries
        zf.write(SINGBOX_EXE, "sing-box.exe")
        zf.write(WINSW_EXE,   "winsw3.exe")
        # WinSW config (with subscription URL filled in)
        zf.writestr("winsw3.xml", _winsw_xml(sub_url, client_name))
        # CMD helper scripts
        for name, content in _SCRIPTS.items():
            zf.writestr(name, content)

    return buf.getvalue()
