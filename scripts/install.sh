#!/bin/bash
# ============================================================
# Singbox UI Bot — Full Installation Script
# Supports: Debian 11/12/13, Ubuntu 22.04/24.04
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
prompt()  { echo -e "${BLUE}[INPUT]${NC} $*"; }

INSTALL_DIR="/opt/singbox-ui-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ─── Checks ───────────────────────────────────────────────────────────────────

check_root() {
    [[ $EUID -eq 0 ]] || error "Запустите скрипт от имени root: sudo bash install.sh"
}

check_os() {
    . /etc/os-release
    case "$ID $VERSION_ID" in
        "debian 11"|"debian 12"|"debian 13"|"ubuntu 22.04"|"ubuntu 24.04") ;;
        *) warn "Неподдерживаемая ОС: $ID $VERSION_ID. Продолжаем на свой риск." ;;
    esac
    info "ОС: $PRETTY_NAME"
}

check_not_installed() {
    if [[ -f "$INSTALL_DIR/.installed" ]]; then
        warn "Бот уже установлен в $INSTALL_DIR"
        read -p "Переустановить? [y/N]: " ans
        [[ "$ans" =~ ^[Yy]$ ]] || exit 0
    fi
}

# ─── Packages ─────────────────────────────────────────────────────────────────

install_packages() {
    info "Обновление пакетов..."
    apt-get update -qq

    info "Установка зависимостей..."
    apt-get install -y --no-install-recommends \
        curl wget git ca-certificates gnupg lsb-release \
        certbot python3-certbot-nginx ufw openssl jq

    # Docker
    if ! command -v docker &>/dev/null; then
        info "Установка Docker..."
        curl -fsSL https://get.docker.com | bash
        systemctl enable docker
        systemctl start docker
    else
        info "Docker уже установлен: $(docker --version)"
    fi

    # Docker Compose plugin
    if ! docker compose version &>/dev/null; then
        info "Установка Docker Compose plugin..."
        apt-get install -y docker-compose-plugin
    fi
}

# ─── Security ─────────────────────────────────────────────────────────────────

setup_firewall() {
    info "Настройка UFW..."
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow "$SSH_PORT/tcp"
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 53/tcp
    ufw allow 53/udp
    ufw --force enable
    info "UFW настроен"
}

# ─── SSL Certificate ──────────────────────────────────────────────────────────

issue_ssl() {
    info "Получение SSL сертификата для $DOMAIN..."
    certbot certonly --standalone \
        -d "$DOMAIN" \
        --email "$EMAIL" \
        --agree-tos \
        --non-interactive \
        --quiet \
        || warn "certbot завершился с ошибкой. Проверьте DNS и доступность порта 80."
}

# ─── .env generation ──────────────────────────────────────────────────────────

generate_env() {
    info "Генерация .env файла..."
    SECRET_KEY=$(openssl rand -hex 32)
    FED_SECRET=$(openssl rand -hex 32)

    cat > "$INSTALL_DIR/.env" <<EOF
# Telegram Bot
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS

# s-ui API
SUI_URL=http://sui:2095
SUI_USERNAME=admin
SUI_PASSWORD=$(openssl rand -hex 12)
SUI_TOKEN=

# AdGuard Home
ADGUARD_URL=http://adguard:3000
ADGUARD_USER=admin
ADGUARD_PASSWORD=$(openssl rand -hex 12)

# Nginx & SSL
DOMAIN=$DOMAIN
EMAIL=$EMAIL
STUB_THEME=default

# Federation
FEDERATION_SECRET=$FED_SECRET
BOT_PUBLIC_URL=https://$DOMAIN

# Security
SECRET_KEY=$SECRET_KEY

# Timezone
TZ=$TIMEZONE

# Bot language
BOT_LANG=$BOT_LANG

# Webhook (via nginx)
WEBHOOK_HOST=https://$DOMAIN
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8080
EOF
    chmod 600 "$INSTALL_DIR/.env"
    info ".env создан"
}

# ─── Nginx initial config ─────────────────────────────────────────────────────

setup_nginx_init() {
    mkdir -p "$INSTALL_DIR/nginx/conf.d"
    mkdir -p "$INSTALL_DIR/nginx/logs"
    # Minimal HTTP-only config until bot generates the full one
    cat > "$INSTALL_DIR/nginx/conf.d/init.conf" <<NGINXEOF
server {
    listen 80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location /webhook {
        proxy_pass http://bot:8080/webhook;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location / {
        root /var/www/stubs/default;
        index index.html;
    }
}
NGINXEOF
}

# ─── Data dirs ────────────────────────────────────────────────────────────────

setup_dirs() {
    mkdir -p "$INSTALL_DIR/data/sui"
    mkdir -p "$INSTALL_DIR/data/certs"
    mkdir -p "$INSTALL_DIR/data/adguard/work"
    mkdir -p "$INSTALL_DIR/data/adguard/conf"
    chmod -R 755 "$INSTALL_DIR/data"
}

# ─── Collect user input ───────────────────────────────────────────────────────

collect_input() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "       Singbox UI Bot — Установка"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    prompt "Telegram Bot Token (получить у @BotFather):"
    read -r BOT_TOKEN
    [[ -n "$BOT_TOKEN" ]] || error "BOT_TOKEN не может быть пустым"

    prompt "Ваш Telegram ID (администратор, узнать у @userinfobot):"
    read -r ADMIN_IDS
    [[ -n "$ADMIN_IDS" ]] || error "ADMIN_IDS не может быть пустым"

    prompt "Домен (например: vpn.example.com):"
    read -r DOMAIN
    [[ -n "$DOMAIN" ]] || error "DOMAIN не может быть пустым"

    prompt "Email для Let's Encrypt:"
    read -r EMAIL
    [[ -n "$EMAIL" ]] || error "EMAIL не может быть пустым"

    prompt "SSH порт (по умолчанию 22):"
    read -r SSH_PORT
    SSH_PORT="${SSH_PORT:-22}"

    prompt "Часовой пояс (например: Europe/Moscow, UTC):"
    read -r TIMEZONE
    TIMEZONE="${TIMEZONE:-UTC}"

    prompt "Язык бота [ru/en] (по умолчанию ru):"
    read -r BOT_LANG
    BOT_LANG="${BOT_LANG:-ru}"
}

# ─── Deploy ───────────────────────────────────────────────────────────────────

deploy() {
    info "Копирование файлов в $INSTALL_DIR..."
    if [[ "$PROJECT_DIR" != "$INSTALL_DIR" ]]; then
        rsync -a --exclude='.git' --exclude='__pycache__' \
            "$PROJECT_DIR/" "$INSTALL_DIR/"
    fi
    cd "$INSTALL_DIR"

    info "Запуск контейнеров..."
    docker compose pull --quiet
    docker compose up -d --build

    touch "$INSTALL_DIR/.installed"
    info "Деплой завершён"
}

# ─── Post-install ─────────────────────────────────────────────────────────────

post_install() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}  ✅ Установка завершена успешно!${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  📱 Откройте Telegram и найдите вашего бота"
    echo "  🌐 Домен: https://$DOMAIN"
    echo ""
    echo "  Статус контейнеров:"
    docker compose -f "$INSTALL_DIR/docker-compose.yml" ps
    echo ""
    echo "  Полезные команды:"
    echo "    docker compose -C $INSTALL_DIR logs -f bot    # Логи бота"
    echo "    docker compose -C $INSTALL_DIR restart        # Рестарт"
    echo "    bash $INSTALL_DIR/scripts/update.sh           # Обновление"
    echo ""
    echo "  ⚠️  После запуска бота:"
    echo "    1. Войдите в Telegram бот и откройте раздел 🌐 Nginx"
    echo "    2. Нажмите '⚙️ Настроить' для генерации конфига"
    echo "    3. Нажмите '🔒 SSL сертификат' для Let's Encrypt"
    echo ""
}

# ─── Setup certbot renewal cron ───────────────────────────────────────────────

setup_cron() {
    info "Настройка автообновления SSL..."
    (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet --post-hook 'docker exec singbox_nginx nginx -s reload'") | crontab -
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    check_root
    check_os
    check_not_installed
    collect_input
    install_packages
    setup_firewall
    setup_dirs
    issue_ssl
    generate_env
    setup_nginx_init
    setup_cron
    deploy
    post_install
}

main "$@"
