"""
Backup helpers for API, bot-triggered maintenance tasks, and restore bundles.

The app container can always read mounted runtime state (sing-box config, nginx,
AdGuard, DB volume). When the host install root is mounted at
`/opt/singbox-ui-bot`, we also back up the real `.env` file and can schedule a
detached restore helper that survives the app container restart.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from api.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_DATA_DIR = BASE_DIR / "data"
HOST_DATA_DIR = BASE_DIR / "host_data"
NGINX_DIR = BASE_DIR / "nginx"
INSTALL_DIR = Path("/opt/singbox-ui-bot")
HOST_ENV_FILE = INSTALL_DIR / ".env"
RECOVERY_DIR = INSTALL_DIR / "data" / "recovery"

BACKUP_FORMAT = "singbox-ui-bot-backup-v2"
MAX_RESTORE_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_RESTORE_UNPACKED_BYTES = 250 * 1024 * 1024
RESTORE_HELPER_PREFIX = "singbox_restore_"
APP_CONTAINER_CANDIDATES = [name for name in (os.getenv("HOSTNAME"), "singbox_app") if name]
REQUIRED_RESTORE_ENTRIES = {
    ".env",
    "manifest.json",
    "config/sing-box/config.json",
    "data/app.db",
}

_ENV_EXPORT_GROUPS = [
    (
        "Telegram Bot",
        [
            ("BOT_TOKEN", settings.bot_token),
        ],
    ),
    (
        "API Auth",
        [
            ("INTERNAL_TOKEN", settings.internal_token),
            ("JWT_SECRET", settings.jwt_secret),
            ("JWT_EXPIRE_MINUTES", settings.jwt_expire_minutes),
        ],
    ),
    (
        "Web UI",
        [
            ("WEB_ADMIN_USER", settings.web_admin_user),
            ("WEB_ADMIN_PASSWORD", settings.web_admin_password),
        ],
    ),
    (
        "Sing-Box",
        [
            ("SINGBOX_CONFIG_PATH", settings.singbox_config_path),
            ("SINGBOX_CONTAINER", settings.singbox_container),
        ],
    ),
    (
        "AdGuard Home",
        [
            ("ADGUARD_URL", settings.adguard_url),
            ("ADGUARD_USER", settings.adguard_user),
            ("ADGUARD_PASSWORD", settings.adguard_password),
        ],
    ),
    (
        "Federation",
        [
            ("FEDERATION_SECRET", settings.federation_secret),
            ("BOT_PUBLIC_URL", settings.bot_public_url),
        ],
    ),
    (
        "Security",
        [
            ("SECRET_KEY", settings.secret_key),
        ],
    ),
    (
        "Webhook",
        [
            ("WEBHOOK_HOST", settings.webhook_host),
            ("WEBHOOK_PATH", settings.webhook_path),
            ("WEBHOOK_PORT", settings.webhook_port),
            ("WEBHOOK_SECRET", settings.webhook_secret),
        ],
    ),
]

_SINGLE_FILES = [
    (Path(settings.singbox_config_path), "config/sing-box/config.json"),
    (Path(settings.adguard_config_path), "config/adguard/AdGuardHome.yaml"),
    (HOST_DATA_DIR / "adguard_admin_password", "data/adguard_admin_password"),
    (HOST_DATA_DIR / "ssh_port", "data/ssh_port"),
    (NGINX_DIR / ".banned_ips.json", "nginx/.banned_ips.json"),
    (NGINX_DIR / ".web_ui_enabled", "nginx/.web_ui_enabled"),
    (NGINX_DIR / ".site_enabled", "nginx/.site_enabled"),
    (NGINX_DIR / "conf.d" / "singbox.conf", "nginx/conf.d/singbox.conf"),
    (NGINX_DIR / "htpasswd" / ".htpasswd", "nginx/htpasswd/.htpasswd"),
]

_DIRECTORIES = [
    (NGINX_DIR / "override", "nginx/override"),
    (NGINX_DIR / "certs", "nginx/certs"),
]


class RestoreError(RuntimeError):
    """Raised when a restore archive cannot be validated or scheduled."""


def export_env_text() -> str:
    lines = [
        "# Auto-generated recovery export for singbox-ui-bot",
        "# Restore with: singbox-ui-bot restore /path/to/backup.zip",
        "",
    ]
    for title, pairs in _ENV_EXPORT_GROUPS:
        lines.append(f"# {title}")
        for key, value in pairs:
            rendered = "" if value is None else str(value)
            lines.append(f"{key}={rendered}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_restore_notes() -> str:
    return "\n".join(
        [
            "singbox-ui-bot restore workflow",
            "",
            "1. Install singbox-ui-bot on the new server first.",
            "2. Copy this ZIP to the new server, or upload it via Web UI / Telegram Maintenance.",
            "3. Restore from one of the supported entry points:",
            "   - singbox-ui-bot restore /path/to/backup.zip",
            "   - Web UI -> Maintenance -> Backup -> Restore from ZIP",
            "   - Telegram -> Maintenance -> Restore ZIP",
            "4. The restore job will replace .env, config, DB, AdGuard state,",
            "   and Nginx state, then restart the stack.",
            "",
        ]
    )


def build_manifest(entries: Iterable[str]) -> str:
    payload = {
        "format": BACKUP_FORMAT,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "entries": list(entries),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _write_file(zf: zipfile.ZipFile, src: Path, arcname: str, included: List[str]) -> None:
    if not src.exists() or not src.is_file():
        return
    zf.write(src, arcname)
    included.append(arcname)


def _write_directory(zf: zipfile.ZipFile, src_dir: Path, arc_prefix: str, included: List[str]) -> None:
    if not src_dir.exists() or not src_dir.is_dir():
        return
    for item in sorted(src_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(src_dir).as_posix()
        arcname = f"{arc_prefix}/{rel}"
        zf.write(item, arcname)
        included.append(arcname)


def _write_sqlite_snapshot(zf: zipfile.ZipFile, src: Path, arcname: str, included: List[str]) -> None:
    if not src.exists() or not src.is_file():
        return

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
        dest = sqlite3.connect(tmp.name)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        zf.write(tmp.name, arcname)
    included.append(arcname)


def _env_backup_bytes() -> bytes:
    if HOST_ENV_FILE.exists() and HOST_ENV_FILE.is_file():
        return HOST_ENV_FILE.read_bytes()
    return export_env_text().encode("utf-8")


def build_backup_zip() -> bytes:
    included: List[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(".env", _env_backup_bytes())
        included.append(".env")

        _write_sqlite_snapshot(zf, APP_DATA_DIR / "app.db", "data/app.db", included)

        for src, arcname in _SINGLE_FILES:
            _write_file(zf, src, arcname, included)

        for src_dir, arc_prefix in _DIRECTORIES:
            _write_directory(zf, src_dir, arc_prefix, included)

        zf.writestr("RESTORE.txt", build_restore_notes())
        included.append("RESTORE.txt")

        zf.writestr("manifest.json", build_manifest(sorted(included)))

    buf.seek(0)
    return buf.getvalue()


def inspect_backup_zip(content: bytes) -> dict:
    if len(content) > MAX_RESTORE_UPLOAD_BYTES:
        raise RestoreError("Backup archive is too large (max 100 MB).")

    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
            names: set[str] = set()
            total_unpacked = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                normalized = Path(info.filename)
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise RestoreError("Backup archive contains unsafe paths.")
                arcname = normalized.as_posix().strip("/")
                if not arcname:
                    continue
                names.add(arcname)
                total_unpacked += info.file_size
                if total_unpacked > MAX_RESTORE_UNPACKED_BYTES:
                    raise RestoreError("Backup archive expands to more than 250 MB.")

            if "manifest.json" not in names:
                raise RestoreError("Unsupported backup format: manifest.json is missing.")

            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RestoreError("manifest.json is corrupted.") from exc
    except zipfile.BadZipFile as exc:
        raise RestoreError("Invalid ZIP archive.") from exc

    if manifest.get("format") != BACKUP_FORMAT:
        raise RestoreError("Unsupported backup format. Create a new recovery ZIP first.")

    missing = sorted(REQUIRED_RESTORE_ENTRIES - names)
    if missing:
        raise RestoreError(
            "Backup archive is missing required files: " + ", ".join(missing)
        )

    return {"manifest": manifest, "entries": sorted(names)}


def ensure_install_root() -> Path:
    if not INSTALL_DIR.exists() or not INSTALL_DIR.is_dir():
        raise RestoreError(
            "Host install root is not mounted inside the app container. "
            "Update docker-compose and recreate the app container first."
        )
    compose_file = INSTALL_DIR / "docker-compose.yml"
    if not compose_file.exists():
        raise RestoreError(f"docker-compose.yml not found in {INSTALL_DIR}")
    scripts_dir = INSTALL_DIR / "scripts"
    if not scripts_dir.exists():
        raise RestoreError(f"scripts/ not found in {INSTALL_DIR}")
    return INSTALL_DIR


async def _run(*cmd: str, timeout: int = 60) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0, stdout.decode(errors="replace")
    except asyncio.TimeoutError:
        return False, "timeout"
    except Exception as exc:
        return False, str(exc)


async def _current_app_image() -> str:
    for candidate in APP_CONTAINER_CANDIDATES:
        ok, out = await _run("docker", "inspect", "--format", "{{.Config.Image}}", candidate)
        image = out.strip()
        if ok and image:
            return image
    raise RestoreError("Cannot determine the running app image for the restore helper.")


async def _start_restore_helper(backup_path: Path, log_path: Path) -> tuple[str, str]:
    image = await _current_app_image()
    job_name = f"{RESTORE_HELPER_PREFIX}{datetime.now().strftime('%Y%m%d%H%M%S')}"
    helper_cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        job_name,
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        f"{INSTALL_DIR}:{INSTALL_DIR}",
        image,
        "sh",
        str(INSTALL_DIR / "scripts" / "restore-worker.sh"),
        str(backup_path),
        str(log_path),
    ]
    ok, out = await _run(*helper_cmd, timeout=30)
    if not ok:
        raise RestoreError(f"Failed to start restore helper: {out.strip() or 'unknown error'}")
    return job_name, out.strip()


async def schedule_restore_job(
    content: bytes,
    filename: str | None = None,
    *,
    create_safety_backup: bool = True,
) -> dict:
    install_dir = ensure_install_root()
    inspected = inspect_backup_zip(content)

    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_path = RECOVERY_DIR / f"restore_upload_{timestamp}.zip"
    log_path = RECOVERY_DIR / f"restore_{timestamp}.log"
    upload_path.write_bytes(content)

    safety_backup_path: Path | None = None
    if create_safety_backup:
        safety_backup_path = RECOVERY_DIR / f"safety_backup_{timestamp}.zip"
        safety_backup_path.write_bytes(build_backup_zip())

    job_name, container_id = await _start_restore_helper(upload_path, log_path)

    return {
        "scheduled": True,
        "message": (
            "Restore job started. Web UI and Telegram bot may disconnect for "
            "30-60 seconds while the stack is recreated."
        ),
        "source_file": filename or upload_path.name,
        "format": inspected["manifest"].get("format"),
        "backup_created_at": inspected["manifest"].get("created_at"),
        "entries_count": len(inspected["entries"]),
        "create_safety_backup": create_safety_backup,
        "safety_backup_path": str(safety_backup_path) if safety_backup_path else None,
        "restore_log_path": str(log_path),
        "helper_container": job_name,
        "helper_container_id": container_id,
        "install_dir": str(install_dir),
        "expected_downtime_seconds": 60,
    }
