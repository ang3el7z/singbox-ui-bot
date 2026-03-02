#!/bin/bash
# ============================================================
# Singbox UI Bot — Full Installation Script
# Supports: Debian 11/12/13, Ubuntu 22.04/24.04
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
#   OR:
#   git clone https://github.com/ang3el7z/singbox-ui-bot /opt/singbox-ui-bot
#   bash /opt/singbox-ui-bot/scripts/install.sh
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
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow "$SSH_PORT/tcp"
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

# ─── SSL Certificate ──────────────────────────────────────────────────────────

issue_ssl() {
    info "Obtaining SSL certificate for $DOMAIN..."
    # Stop nginx if running to free port 80
    systemctl stop nginx 2>/dev/null || true

    certbot certonly --standalone \
        -d "$DOMAIN" \
        --email "$EMAIL" \
        --agree-tos \
        --non-interactive \
        --quiet \
        && {
            # Symlink/copy certs into nginx/certs so the nginx container can read them
            CERT_SRC="/etc/letsencrypt/live/$DOMAIN"
            CERT_DST="$INSTALL_DIR/nginx/certs/live/$DOMAIN"
            mkdir -p "$CERT_DST"
            # Use bind-mount friendly copies (certbot produces symlinks; resolve them)
            cp -L "$CERT_SRC/fullchain.pem" "$CERT_DST/fullchain.pem"
            cp -L "$CERT_SRC/privkey.pem"   "$CERT_DST/privkey.pem"
            chmod 644 "$CERT_DST/fullchain.pem"
            chmod 600 "$CERT_DST/privkey.pem"
            info "SSL certificate saved to $CERT_DST"

            # Add renewal hook to re-copy after renewal
            mkdir -p /etc/letsencrypt/renewal-hooks/deploy
            cat > /etc/letsencrypt/renewal-hooks/deploy/copy-to-singbox.sh <<HOOK
#!/bin/bash
CERT_SRC="/etc/letsencrypt/live/$DOMAIN"
CERT_DST="$INSTALL_DIR/nginx/certs/live/$DOMAIN"
mkdir -p "\$CERT_DST"
cp -L "\$CERT_SRC/fullchain.pem" "\$CERT_DST/fullchain.pem"
cp -L "\$CERT_SRC/privkey.pem"   "\$CERT_DST/privkey.pem"
chmod 644 "\$CERT_DST/fullchain.pem"
chmod 600 "\$CERT_DST/privkey.pem"
docker exec singbox_nginx nginx -s reload 2>/dev/null || true
HOOK
            chmod +x /etc/letsencrypt/renewal-hooks/deploy/copy-to-singbox.sh
        } || warn "certbot failed. Check DNS A-record and port 80 availability. You can issue SSL later via the bot."
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

    # If AdGuard runs in docker the hostname is 'adguard'; otherwise assume localhost
    if [[ "${USE_ADGUARD_DOCKER,,}" == "y" ]]; then
        ADGUARD_HOST="http://adguard:3000"
    else
        ADGUARD_HOST="http://localhost:3000"
    fi

    # Nginx container name for docker exec commands (reload, test config)
    if [[ "${USE_NGINX_DOCKER,,}" == "y" ]]; then
        NGINX_CONTAINER_NAME="singbox_nginx"
    else
        NGINX_CONTAINER_NAME=""
    fi

    cat > "$INSTALL_DIR/.env" <<EOF
# Telegram Bot
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS

# API Auth (auto-generated, do not share)
INTERNAL_TOKEN=$INTERNAL_TOKEN
JWT_SECRET=$JWT_SECRET
JWT_EXPIRE_MINUTES=10080

# Web UI credentials (change after first login!)
WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=$WEB_PASS

# Sing-Box
SINGBOX_CONFIG_PATH=/etc/sing-box/config.json
SINGBOX_CONTAINER=singbox_core

# AdGuard Home (set ADGUARD_URL='' to disable AdGuard integration)
ADGUARD_URL=$ADGUARD_HOST
ADGUARD_USER=admin
ADGUARD_PASSWORD=$AG_PASS

# Nginx & SSL
DOMAIN=$DOMAIN
EMAIL=$EMAIL
# Leave empty if using host nginx (not docker container)
NGINX_CONTAINER=$NGINX_CONTAINER_NAME

# Federation (auto-generated, must match across linked bots)
FEDERATION_SECRET=$FED_SECRET
BOT_PUBLIC_URL=https://$DOMAIN

# Docker Compose profiles (comma-separated: nginx,adguard)
COMPOSE_PROFILES=$COMPOSE_PROFILES

# App
SECRET_KEY=$SECRET_KEY
TZ=$TIMEZONE
BOT_LANG=$BOT_LANG
WEBHOOK_HOST=https://$DOMAIN
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8080
EOF
    chmod 600 "$INSTALL_DIR/.env"
    info ".env created"
}

# ─── Initial Nginx config ─────────────────────────────────────────────────────

setup_nginx_init() {
    # Only write if a full config does not yet exist
    if [[ -f "$INSTALL_DIR/nginx/conf.d/singbox.conf" ]]; then
        info "Nginx config already exists, skipping init"
        return
    fi
    info "Writing initial Nginx config..."

    # Check if SSL cert is available
    CERT_DST="$INSTALL_DIR/nginx/certs/live/$DOMAIN"
    if [[ -f "$CERT_DST/fullchain.pem" ]]; then
        SSL_CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
        SSL_KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
        PROTOCOL="ssl http2"
        SSL_BLOCK="ssl_certificate     $CERT_DST/fullchain.pem;
    ssl_certificate_key $CERT_DST/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;"
    else
        PROTOCOL=""
        SSL_BLOCK=""
    fi

    cat > "$INSTALL_DIR/nginx/conf.d/singbox.conf" <<NGINXEOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    server_tokens off;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /api/ {
        proxy_pass http://app:8080/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /webhook {
        proxy_pass http://app:8080/webhook;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location /web/ {
        alias /var/www/web/;
        try_files \$uri \$uri/ /web/index.html;
    }

    location /federation/ {
        proxy_pass http://app:8080/federation/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    location = / {
        try_files /index.html @auth;
    }

    location @auth {
        auth_basic           "Restricted Content";
        auth_basic_user_file /etc/nginx/htpasswd/.htpasswd;
        try_files            /dev/null =403;
    }
}
NGINXEOF
    info "Initial Nginx config written"
}

# ─── Collect user input ───────────────────────────────────────────────────────

collect_input() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "     Singbox UI Bot — Installation"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    prompt "Telegram Bot Token (get from @BotFather):"
    read -r BOT_TOKEN
    [[ -n "$BOT_TOKEN" ]] || error "BOT_TOKEN cannot be empty"

    prompt "Your Telegram ID (admin, get from @userinfobot):"
    read -r ADMIN_IDS
    [[ -n "$ADMIN_IDS" ]] || error "ADMIN_IDS cannot be empty"

    prompt "Domain (e.g. vpn.example.com) — must have A-record pointing to this server:"
    read -r DOMAIN
    [[ -n "$DOMAIN" ]] || error "DOMAIN cannot be empty"

    prompt "Email for Let's Encrypt:"
    read -r EMAIL
    [[ -n "$EMAIL" ]] || error "EMAIL cannot be empty"

    prompt "SSH port (default 22):"
    read -r SSH_PORT
    SSH_PORT="${SSH_PORT:-22}"

    prompt "Timezone (e.g. Europe/Moscow, UTC):"
    read -r TIMEZONE
    TIMEZONE="${TIMEZONE:-UTC}"

    prompt "Bot language [ru/en] (default ru):"
    read -r BOT_LANG
    BOT_LANG="${BOT_LANG:-ru}"

    echo ""
    echo "  Optional services:"
    echo "  (skip if you already have these installed on the host)"
    echo ""

    prompt "Run Nginx in Docker? [y/N]:"
    read -r USE_NGINX_DOCKER
    USE_NGINX_DOCKER="${USE_NGINX_DOCKER:-n}"

    prompt "Run AdGuard Home in Docker? [y/N]:"
    read -r USE_ADGUARD_DOCKER
    USE_ADGUARD_DOCKER="${USE_ADGUARD_DOCKER:-n}"

    # Build COMPOSE_PROFILES from choices
    COMPOSE_PROFILES=""
    [[ "${USE_NGINX_DOCKER,,}" == "y" ]] && COMPOSE_PROFILES+="nginx,"
    [[ "${USE_ADGUARD_DOCKER,,}" == "y" ]] && COMPOSE_PROFILES+="adguard,"
    COMPOSE_PROFILES="${COMPOSE_PROFILES%,}"   # strip trailing comma
}

# ─── Deploy ───────────────────────────────────────────────────────────────────

deploy() {
    info "Starting containers..."
    cd "$INSTALL_DIR"

    # Build the --profile flags from COMPOSE_PROFILES (comma-separated)
    PROFILE_ARGS=""
    if [[ -n "$COMPOSE_PROFILES" ]]; then
        IFS=',' read -ra _profiles <<< "$COMPOSE_PROFILES"
        for _p in "${_profiles[@]}"; do
            PROFILE_ARGS+=" --profile $_p"
        done
    fi

    docker compose pull --quiet $PROFILE_ARGS || true
    # shellcheck disable=SC2086
    docker compose up -d --build $PROFILE_ARGS
    touch "$INSTALL_DIR/.installed"
    info "Deploy complete"
}

# ─── Post-install ─────────────────────────────────────────────────────────────

setup_cron() {
    info "Setting up SSL auto-renewal cron..."
    (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet") | sort -u | crontab -
}

post_install() {
    # Show generated credentials
    WEB_PASS_SHOWN=$(grep WEB_ADMIN_PASSWORD "$INSTALL_DIR/.env" | cut -d= -f2)
    AG_PASS_SHOWN=$(grep ADGUARD_PASSWORD "$INSTALL_DIR/.env" | cut -d= -f2)

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}  ✅ Installation complete!${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  📱 Telegram: find your bot and send /start"
    echo "  🌐 Web UI:   https://$DOMAIN/web/"
    echo ""
    echo "  🔑 Credentials (save these!):"
    echo "     Web UI login:  admin / $WEB_PASS_SHOWN"
    echo "     AdGuard:       admin / $AG_PASS_SHOWN"
    echo ""
    [[ -n "$COMPOSE_PROFILES" ]] && \
        echo "  Active profiles: $COMPOSE_PROFILES"
    echo ""
    echo "  Container status:"
    docker compose -f "$INSTALL_DIR/docker-compose.yml" ps
    echo ""
    echo "  Useful commands:"
    echo "    docker compose -f $INSTALL_DIR/docker-compose.yml logs -f app    # App logs"
    echo "    docker compose -f $INSTALL_DIR/docker-compose.yml logs -f singbox # Singbox logs"
    echo "    bash $INSTALL_DIR/scripts/update.sh                               # Update"
    echo ""
    echo "  ⚠️  Next steps:"
    echo "    1. Send /menu to your bot → Inbounds → Add inbound (e.g. VLESS Reality)"
    echo "    2. Add clients → download config → import in Sing-Box app"
    echo "    3. Web UI: https://$DOMAIN/web/ — same features in browser"
    echo ""
    echo "  Config file:  $INSTALL_DIR/.env"
    echo "  Sing-Box cfg: $INSTALL_DIR/config/sing-box/config.json"
    echo ""
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    # When the script is run via "curl | bash", stdin is the pipe carrying the
    # script body, so read(1) gets EOF immediately. Reconnect stdin to the
    # controlling terminal so interactive prompts work correctly.
    exec < /dev/tty

    check_root
    check_os
    collect_input
    install_packages
    setup_repo
    setup_dirs
    generate_env
    issue_ssl
    setup_nginx_init
    setup_cron
    deploy
    post_install
}

main "$@"
