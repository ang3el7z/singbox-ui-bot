#!/bin/bash
# ============================================================
# Singbox UI Bot - Update Script
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

INSTALL_DIR="/opt/singbox-ui-bot"
[[ $EUID -eq 0 ]] || error "Run as root: sudo bash update.sh"
[[ -f "$INSTALL_DIR/.installed" ]] || error "Bot is not installed. Run install.sh first"

cd "$INSTALL_DIR"

info "Creating backup before update..."
BACKUP_FILE="$INSTALL_DIR/data/backup_$(date +%Y%m%d_%H%M%S).tar.gz"
tar -czf "$BACKUP_FILE" \
    --exclude="$INSTALL_DIR/data/adguard/work" \
    "$INSTALL_DIR/data/" "$INSTALL_DIR/.env" 2>/dev/null || true
info "Backup: $BACKUP_FILE"

info "Fetching updates..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull origin main
fi

info "Rebuilding containers..."
docker compose pull --quiet
docker compose up -d --build --no-deps bot

if [[ -d "$INSTALL_DIR/.git" ]]; then
    COMMIT="$(git -C "$INSTALL_DIR" rev-parse HEAD 2>/dev/null || true)"
    COMMIT_SHORT="$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || true)"
    REF_NAME="$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    EXACT_TAG="$(git -C "$INSTALL_DIR" describe --tags --exact-match 2>/dev/null || true)"
    DESCRIBE_TAG="$(git -C "$INSTALL_DIR" describe --tags --always --dirty --abbrev=7 2>/dev/null || true)"
    RECORDED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    VERSION_VALUE="${EXACT_TAG:-$DESCRIBE_TAG}"

    if [[ -z "$VERSION_VALUE" ]]; then
        if [[ -n "$REF_NAME" && -n "$COMMIT_SHORT" ]]; then
            VERSION_VALUE="${REF_NAME}@${COMMIT_SHORT}"
        else
            VERSION_VALUE="dev"
        fi
    fi

    mkdir -p "$INSTALL_DIR/data"
    cat > "$INSTALL_DIR/data/install_version.json" <<EOF
{
  "version": "$VERSION_VALUE",
  "ref": "$REF_NAME",
  "commit": "$COMMIT",
  "commit_short": "$COMMIT_SHORT",
  "recorded_at": "$RECORDED_AT",
  "recorded_by": "update.sh"
}
EOF
    info "Recorded install version: $VERSION_VALUE"
fi

info "Cleaning unused Docker images..."
docker image prune -f

echo ""
echo -e "${GREEN}Update completed${NC}"
docker compose ps
