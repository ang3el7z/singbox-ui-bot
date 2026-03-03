#!/bin/bash
# ============================================================
# Singbox UI Bot — Full Installation Script
# Supports: Debian 11/12/13, Ubuntu 22.04/24.04
# Usage (non-interactive only — token required):
#   curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash -s -- YOUR_BOT_TOKEN
#   Or: BOT_TOKEN=123:ABC bash install.sh
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()   { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
prompt() { echo -e "${BLUE}[INPUT]${NC} $*"; }

REPO_URL="https://github.com/ang3el7z/singbox-ui-bot.git"
INSTALL_DIR="/opt/singbox-ui-bot"

# Token from first argument or from environment (required)
[[ -n "${1:-}" ]] && export BOT_TOKEN="$1"

# ─── Checks ───────────────────────────────────────────────────────────────────

check_root() {
    [[ $EUID -eq 0 ]] || error "Run as root: sudo bash install.sh"
}

check_os() {
    if [[ ! -f /etc/debian_version ]] && [[ ! -f /etc/ubuntu_version ]]; then
        warn "Tested on Debian/Ubuntu. Other distros may work but are unsupported."
    fi
}

# ─── Clone or update repo ─────────────────────────────────────────────────────

setup_repo() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Repo already cloned at $INSTALL_DIR, pulling latest..."
        git -C "$INSTALL_DIR" pull --ff-only || warn "git pull failed; using existing files"
    elif [[ -d "$INSTALL_DIR" ]] && [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
        info "Files already at $INSTALL_DIR (not a git repo), skipping clone"
    else
        info "Cloning repository to $INSTALL_DIR..."
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    cd "$INSTALL_DIR"
}

# ─── Packages ─────────────────────────────────────────────────────────────────

install_packages() {
    info "Updating packages and installing dependencies..."
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        curl wget git ca-certificates gnupg lsb-release \
        certbot python3-certbot-nginx ufw openssl jq

    if ! command -v docker &>/dev/null; then
        info "Installing Docker..."
        curl -fsSL https://get.docker.com | bash
        systemctl enable docker
        systemctl start docker
    else
        info "Docker already installed: $(docker --version)"
    fi

    if ! docker compose version &>/dev/null; then
        info "Installing Docker Compose plugin..."
        apt-get install -y docker-compose-plugin
    fi
}

# ─── Firewall ─────────────────────────────────────────────────────────────────

setup_firewall() {
    info "Configuring UFW firewall..."
    SSH_PORT=22
    if [[ -f "$INSTALL_DIR/data/ssh_port" ]] && [[ -r "$INSTALL_DIR/data/ssh_port" ]]; then
        read -r SSH_PORT < "$INSTALL_DIR/data/ssh_port" || true
        [[ "$SSH_PORT" =~ ^[0-9]+$ ]] && [[ "$SSH_PORT" -ge 1 ]] && [[ "$SSH_PORT" -le 65535 ]] || SSH_PORT=22
    fi
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow "${SSH_PORT}/tcp"   # SSH — change via bot (Server → SSH port), then run: singbox-ui-bot firewall
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 53/tcp
    ufw allow 53/udp
    ufw --force enable
    info "UFW configured"
}

# ─── Directories ──────────────────────────────────────────────────────────────

setup_dirs() {
    info "Creating directories..."
    mkdir -p "$INSTALL_DIR/data"
    mkdir -p "$INSTALL_DIR/nginx/conf.d"
    mkdir -p "$INSTALL_DIR/nginx/logs"
    mkdir -p "$INSTALL_DIR/nginx/override"
    mkdir -p "$INSTALL_DIR/nginx/htpasswd"
    mkdir -p "$INSTALL_DIR/nginx/certs"
    mkdir -p "$INSTALL_DIR/config/sing-box/templates"
    mkdir -p "$INSTALL_DIR/subs"
    chmod -R 755 "$INSTALL_DIR/data" "$INSTALL_DIR/nginx"
}

# ─── .env generation ──────────────────────────────────────────────────────────

generate_env() {
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        warn ".env already exists, skipping generation. Edit it manually if needed."
        return
    fi
    info "Generating .env file..."

    SECRET_KEY=$(openssl rand -hex 32)
    FED_SECRET=$(openssl rand -hex 32)
    INTERNAL_TOKEN=$(openssl rand -hex 32)
    JWT_SECRET=$(openssl rand -hex 32)
    WEB_PASS=$(openssl rand -hex 12)
    AG_PASS=$(openssl rand -hex 12)

    cat > "$INSTALL_DIR/.env" <<EOF
# ── Telegram Bot ──────────────────────────────────────────────────────────────
BOT_TOKEN=$BOT_TOKEN
# No ADMIN_IDS — first /start registers the owner as admin via bot wizard

# ── API Auth (auto-generated secrets — do not share) ──────────────────────────
INTERNAL_TOKEN=$INTERNAL_TOKEN
JWT_SECRET=$JWT_SECRET
JWT_EXPIRE_MINUTES=10080

# ── Web UI initial credentials (change after first login!) ────────────────────
WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=$WEB_PASS

# ── Sing-Box ──────────────────────────────────────────────────────────────────
SINGBOX_CONFIG_PATH=/etc/sing-box/config.json
SINGBOX_CONTAINER=singbox_core

# ── AdGuard Home ──────────────────────────────────────────────────────────────
ADGUARD_URL=http://adguard:3000
ADGUARD_USER=admin
ADGUARD_PASSWORD=$AG_PASS

# ── Federation ────────────────────────────────────────────────────────────────
FEDERATION_SECRET=$FED_SECRET
BOT_PUBLIC_URL=

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY=$SECRET_KEY

# ── Webhook (empty = polling mode; set after domain is configured) ────────────
WEBHOOK_HOST=
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8080

# ── NOTE ──────────────────────────────────────────────────────────────────────
# Domain, timezone and bot language are stored ONLY in the database.
# Set them via the /start wizard in the bot — no .env changes needed.
EOF
    chmod 600 "$INSTALL_DIR/.env"
    info ".env created"
}

# ─── Initial Nginx config (IP-only, no domain, no SSL) ────────────────────────
#
# This bootstrap config keeps the app reachable over plain HTTP on port 80.
# When the user sets a domain via the bot wizard, nginx_service.py regenerates
# this file with the proper server_name, SSL, and secret paths.

setup_nginx_init() {
    if [[ -f "$INSTALL_DIR/nginx/conf.d/singbox.conf" ]]; then
        info "Nginx config already exists, skipping init"
        return
    fi
    info "Writing bootstrap Nginx config (HTTP, IP-based)..."

    cat > "$INSTALL_DIR/nginx/conf.d/singbox.conf" <<'NGINXEOF'
# Bootstrap config — replaced automatically when domain is set via the bot.
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    server_tokens off;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /api/ {
        proxy_pass http://app:8080/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /webhook {
        proxy_pass http://app:8080/webhook;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /web/ {
        alias /var/www/web/;
        try_files $uri $uri/ /web/index.html;
    }

    location /federation/ {
        proxy_pass http://app:8080/federation/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        return 401;
    }
}
NGINXEOF
    info "Bootstrap Nginx config written"
}

# ─── Collect user input ───────────────────────────────────────────────────────

collect_input() {
    if [[ -z "${BOT_TOKEN:-}" ]]; then
        error "BOT_TOKEN is required. Run:\n  curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash -s -- YOUR_BOT_TOKEN\nOr: BOT_TOKEN=your_token bash install.sh"
    fi
    info "Using BOT_TOKEN from argument or environment"
}

# ─── Kernel / sysctl ──────────────────────────────────────────────────────────

setup_sysctl() {
    # sing-box runs with network_mode: host — sysctl must be set on the HOST,
    # not inside the container (Docker rejects it with "not allowed in host network namespace").
    info "Enabling IP forwarding on host..."
    sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

    # Persist across reboots
    if ! grep -q "net.ipv4.ip_forward" /etc/sysctl.conf 2>/dev/null; then
        echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
    else
        sed -i 's/^#*\s*net\.ipv4\.ip_forward\s*=.*/net.ipv4.ip_forward=1/' /etc/sysctl.conf
    fi

    # Same for IPv6 forwarding (needed for dual-stack VPN setups)
    sysctl -w net.ipv6.conf.all.forwarding=1 >/dev/null 2>&1 || true
    if ! grep -q "net.ipv6.conf.all.forwarding" /etc/sysctl.conf 2>/dev/null; then
        echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.conf
    else
        sed -i 's/^#*\s*net\.ipv6\.conf\.all\.forwarding\s*=.*/net.ipv6.conf.all.forwarding=1/' /etc/sysctl.conf
    fi

    info "IP forwarding enabled (IPv4 + IPv6)"
}


# ─── Free ports 80/443 (like vpnbot: only Docker nginx binds them) ──────────────
#
# If nginx or apache is running on the host, our container cannot bind 80/443.
# Stop and disable them so Docker has exclusive use for masking.

release_ports_80_443() {
    local freed=
    for svc in nginx apache2; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            info "Stopping and disabling $svc on host so Docker can use ports 80/443..."
            systemctl stop "$svc" 2>/dev/null || true
            systemctl disable "$svc" 2>/dev/null || true
            freed=1
        fi
    done
    if [[ -n "$freed" ]]; then
        info "Ports 80/443 released for Docker."
    fi
    # Optional: check if something else is still listening
    if command -v ss &>/dev/null; then
        if ss -tlnp 2>/dev/null | grep -q -E ':80\s|:443\s'; then
            warn "Port 80 or 443 still in use. Free it manually (e.g. stop the process) and run: docker compose up -d"
        fi
    fi
}

# ─── Deploy ───────────────────────────────────────────────────────────────────

deploy() {
    release_ports_80_443
    info "Starting containers..."
    cd "$INSTALL_DIR"
    docker compose pull --quiet || true
    docker compose up -d --build
    touch "$INSTALL_DIR/.installed"
    info "Deploy complete"
}

# ─── Post-install ─────────────────────────────────────────────────────────────

setup_cron() {
    info "Setting up SSL auto-renewal cron..."
    (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet") | sort -u | crontab -
}

install_cli() {
    info "Installing management CLI → /usr/local/bin/singbox-ui-bot"
    cp "$INSTALL_DIR/scripts/manage.sh" /usr/local/bin/singbox-ui-bot
    chmod +x /usr/local/bin/singbox-ui-bot
    info "You can now run: singbox-ui-bot"
}

post_install() {
    WEB_PASS_SHOWN=$(grep WEB_ADMIN_PASSWORD "$INSTALL_DIR/.env" | cut -d= -f2)
    AG_PASS_SHOWN=$(grep ADGUARD_PASSWORD   "$INSTALL_DIR/.env" | cut -d= -f2)

    # Try to detect the server's public IP for the hint
    SERVER_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}  ✅ Installation complete!${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  📱 Find your bot in Telegram and send /start"
    echo "     The setup wizard will run automatically:"
    echo "       → Choose language"
    echo "       → Choose timezone"
    echo "       → Set domain (or use ${SERVER_IP} with nip.io)"
    echo "     You will be registered as admin."
    echo ""
    echo "  🌐 Web UI will be available after domain is set."
    echo "     (temporary: http://${SERVER_IP}/web/)"
    echo ""
    echo "  🔑 Credentials (save these!):"
    echo "     Web UI login:  admin / $WEB_PASS_SHOWN"
    echo "     AdGuard:       admin / $AG_PASS_SHOWN"
    echo ""
    echo "  Container status:"
    docker compose -f "$INSTALL_DIR/docker-compose.yml" ps
    echo ""
    echo "  ─────────────────────────────────────────"
    echo "  🛠  Management CLI:"
    echo "    singbox-ui-bot            — interactive menu"
    echo "    singbox-ui-bot status     — show status"
    echo "    singbox-ui-bot backup     — create backup"
    echo "    singbox-ui-bot logs       — view logs"
    echo "    singbox-ui-bot restart    — restart containers"
    echo "    singbox-ui-bot update     — pull & rebuild"
    echo "    singbox-ui-bot uninstall  — clean server"
    echo "  ─────────────────────────────────────────"
    echo ""
    echo "  Config: $INSTALL_DIR/.env"
    echo ""
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    check_root
    check_os
    collect_input
    install_packages
    setup_repo
    setup_dirs
    generate_env
    setup_nginx_init
    setup_firewall
    setup_sysctl
    setup_cron
    deploy
    install_cli
    post_install
}

main "$@"
