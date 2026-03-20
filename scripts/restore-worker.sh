#!/bin/sh
set -eu

INSTALL_DIR="/opt/singbox-ui-bot"
BACKUP_ZIP="${1:-}"
LOG_PATH="${2:-$INSTALL_DIR/data/recovery/restore-worker.log}"

if [ -z "$BACKUP_ZIP" ] || [ ! -f "$BACKUP_ZIP" ]; then
    echo "Backup archive not found: ${BACKUP_ZIP:-<empty>}" >&2
    exit 1
fi

mkdir -p "$(dirname "$LOG_PATH")"
exec >"$LOG_PATH" 2>&1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting restore worker"
echo "Backup ZIP: $BACKUP_ZIP"

TMP_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

python3 - "$BACKUP_ZIP" "$TMP_DIR" <<'PYEOF'
import sys
import zipfile
from pathlib import Path

backup_path = Path(sys.argv[1])
target_dir = Path(sys.argv[2])

with zipfile.ZipFile(backup_path, "r") as zf:
    for info in zf.infolist():
        name = Path(info.filename)
        if name.is_absolute() or ".." in name.parts:
            raise SystemExit(f"Unsafe path in backup: {info.filename}")
    zf.extractall(target_dir)
PYEOF

for required in \
    "$TMP_DIR/.env" \
    "$TMP_DIR/config/sing-box/config.json" \
    "$TMP_DIR/data/app.db" \
    "$TMP_DIR/manifest.json"
do
    if [ ! -f "$required" ]; then
        echo "Required restore file missing: $required" >&2
        exit 1
    fi
done

mkdir -p \
    "$INSTALL_DIR/config/sing-box" \
    "$INSTALL_DIR/config/adguard" \
    "$INSTALL_DIR/data" \
    "$INSTALL_DIR/nginx/conf.d" \
    "$INSTALL_DIR/nginx/override" \
    "$INSTALL_DIR/nginx/htpasswd" \
    "$INSTALL_DIR/nginx/certs" \
    "$INSTALL_DIR/nginx/certbot"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Restoring mounted host files"
cp "$TMP_DIR/.env" "$INSTALL_DIR/.env"
chmod 600 "$INSTALL_DIR/.env"
cp "$TMP_DIR/config/sing-box/config.json" "$INSTALL_DIR/config/sing-box/config.json"

if [ -f "$TMP_DIR/config/adguard/AdGuardHome.yaml" ]; then
    cp "$TMP_DIR/config/adguard/AdGuardHome.yaml" "$INSTALL_DIR/config/adguard/AdGuardHome.yaml"
fi
if [ -f "$TMP_DIR/data/adguard_admin_password" ]; then
    cp "$TMP_DIR/data/adguard_admin_password" "$INSTALL_DIR/data/adguard_admin_password"
fi
if [ -f "$TMP_DIR/data/ssh_port" ]; then
    cp "$TMP_DIR/data/ssh_port" "$INSTALL_DIR/data/ssh_port"
fi
if [ -f "$TMP_DIR/nginx/.banned_ips.json" ]; then
    cp "$TMP_DIR/nginx/.banned_ips.json" "$INSTALL_DIR/nginx/.banned_ips.json"
else
    rm -f "$INSTALL_DIR/nginx/.banned_ips.json"
fi
if [ -f "$TMP_DIR/nginx/.site_enabled" ]; then
    cp "$TMP_DIR/nginx/.site_enabled" "$INSTALL_DIR/nginx/.site_enabled"
else
    rm -f "$INSTALL_DIR/nginx/.site_enabled"
fi
if [ -f "$TMP_DIR/nginx/conf.d/singbox.conf" ]; then
    cp "$TMP_DIR/nginx/conf.d/singbox.conf" "$INSTALL_DIR/nginx/conf.d/singbox.conf"
fi
if [ -f "$TMP_DIR/nginx/htpasswd/.htpasswd" ]; then
    cp "$TMP_DIR/nginx/htpasswd/.htpasswd" "$INSTALL_DIR/nginx/htpasswd/.htpasswd"
fi

rm -rf "$INSTALL_DIR/nginx/override"
mkdir -p "$INSTALL_DIR/nginx/override"
if [ -d "$TMP_DIR/nginx/override" ]; then
    cp -a "$TMP_DIR/nginx/override/." "$INSTALL_DIR/nginx/override/"
fi

rm -rf "$INSTALL_DIR/nginx/certs"
mkdir -p "$INSTALL_DIR/nginx/certs"
if [ -d "$TMP_DIR/nginx/certs" ]; then
    cp -a "$TMP_DIR/nginx/certs/." "$INSTALL_DIR/nginx/certs/"
fi

dc() {
    if docker compose version >/dev/null 2>&1; then
        docker compose -f "$INSTALL_DIR/docker-compose.yml" --env-file "$INSTALL_DIR/.env" "$@"
    else
        docker-compose -f "$INSTALL_DIR/docker-compose.yml" --env-file "$INSTALL_DIR/.env" "$@"
    fi
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Recreating containers"
dc up -d --force-recreate app singbox nginx adguard

APP_CID="$(dc ps -q app 2>/dev/null | head -n 1 || true)"
if [ -z "$APP_CID" ]; then
    APP_CID="$(docker ps --filter name=singbox_app -q | head -n 1 || true)"
fi
if [ -z "$APP_CID" ]; then
    echo "App container is not running after recreate" >&2
    exit 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Restoring SQLite database"
docker cp "$TMP_DIR/data/app.db" "$APP_CID:/app/data/app.db"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Restarting stack"
dc restart app singbox nginx adguard

rm -f "$BACKUP_ZIP"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Restore completed successfully"
