"""
Backup helpers for API, bot-triggered maintenance tasks, and restore bundles.

The API container cannot read the host `.env` file directly, so we export the
current environment-derived settings into a synthetic `.env` inside the backup.
This makes the bundle usable for full server recovery on a fresh install.
"""
from __future__ import annotations

import io
import json
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

BACKUP_FORMAT = "singbox-ui-bot-backup-v2"

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
    (NGINX_DIR / ".site_enabled", "nginx/.site_enabled"),
    (NGINX_DIR / "conf.d" / "singbox.conf", "nginx/conf.d/singbox.conf"),
    (NGINX_DIR / "htpasswd" / ".htpasswd", "nginx/htpasswd/.htpasswd"),
]

_DIRECTORIES = [
    (NGINX_DIR / "override", "nginx/override"),
    (NGINX_DIR / "certs", "nginx/certs"),
]


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
            "2. Copy this ZIP to the new server.",
            "3. Run: singbox-ui-bot restore /path/to/backup.zip",
            "4. The CLI will restore .env, config, DB, AdGuard state, Nginx state,",
            "   then restart the stack.",
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


def build_backup_zip() -> bytes:
    included: List[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(".env", export_env_text())
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
