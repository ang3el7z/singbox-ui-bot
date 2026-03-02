#!/bin/bash
# ============================================================
# Singbox UI Bot — Update Script
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
[[ $EUID -eq 0 ]] || error "Запустите от root: sudo bash update.sh"
[[ -f "$INSTALL_DIR/.installed" ]] || error "Бот не установлен. Запустите install.sh"

cd "$INSTALL_DIR"

info "Создание бэкапа перед обновлением..."
BACKUP_FILE="$INSTALL_DIR/data/backup_$(date +%Y%m%d_%H%M%S).tar.gz"
tar -czf "$BACKUP_FILE" \
    --exclude="$INSTALL_DIR/data/adguard/work" \
    "$INSTALL_DIR/data/" "$INSTALL_DIR/.env" 2>/dev/null || true
info "Бэкап: $BACKUP_FILE"

info "Получение обновлений..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull origin main
fi

info "Пересборка контейнеров..."
docker compose pull --quiet
docker compose up -d --build --no-deps bot

info "Очистка неиспользуемых образов..."
docker image prune -f

echo ""
echo -e "${GREEN}✅ Обновление завершено${NC}"
docker compose ps
