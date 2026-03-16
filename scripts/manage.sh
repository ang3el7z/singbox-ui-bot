#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
#  singbox-ui-bot — Management CLI
#  Installed to /usr/local/bin/singbox-ui-bot by install.sh
#
#  Usage:
#    singbox-ui-bot            — interactive menu
#    singbox-ui-bot backup     — quick backup (no menu)
#    singbox-ui-bot status     — quick status (no menu)
#    singbox-ui-bot uninstall  — uninstall with confirmation
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Color helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m';  GREEN='\033[0;32m';  YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m';      RESET='\033[0m'

info()    { echo -e "${CYAN}ℹ  $*${RESET}"; }
success() { echo -e "${GREEN}✔  $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠  $*${RESET}"; }
error()   { echo -e "${RED}✖  $*${RESET}"; }
header()  { echo -e "\n${BOLD}${CYAN}══ $* ══${RESET}\n"; }

# ── Locate installation ───────────────────────────────────────────────────────
INSTALL_DIR="/opt/singbox-ui-bot"

if [[ ! -d "$INSTALL_DIR" ]]; then
    # Try to find it via docker-compose label or .env
    FOUND=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' \
        "$(docker ps --filter name=singbox-ui-bot -q 2>/dev/null | head -1)" 2>/dev/null || true)
    [[ -n "$FOUND" ]] && INSTALL_DIR="$FOUND"
fi

if [[ ! -d "$INSTALL_DIR" ]]; then
    error "Installation directory not found. Expected: $INSTALL_DIR"
    exit 1
fi

cd "$INSTALL_DIR"

# ── Helper: check if docker compose is available ─────────────────────────────
DC() {
    if command -v "docker" &>/dev/null && docker compose version &>/dev/null 2>&1; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

app_container_id() {
    DC ps -a -q app 2>/dev/null | head -1
}

# ── Firewall (apply SSH port from bot/app) ────────────────────────────────────
cmd_firewall() {
    header "Apply firewall (SSH port)"
    PORT_FILE="$INSTALL_DIR/data/ssh_port"
    if [[ -r "$PORT_FILE" ]]; then
        read -r SSH_PORT < "$PORT_FILE" || true
    fi
    [[ "$SSH_PORT" =~ ^[0-9]+$ ]] && [[ "$SSH_PORT" -ge 1 ]] && [[ "$SSH_PORT" -le 65535 ]] || SSH_PORT=22

    info "Allowing SSH on port $SSH_PORT/tcp..."
    ufw allow "${SSH_PORT}/tcp"
    if [[ "$SSH_PORT" != "22" ]]; then
        info "Removing default SSH port 22 from UFW..."
        ufw delete allow 22/tcp 2>/dev/null || true
    fi
    ufw --force enable
    success "Firewall updated. SSH port: $SSH_PORT"
}

# ── Status ────────────────────────────────────────────────────────────────────
cmd_status() {
    header "Status"
    echo -e "${BOLD}Installation directory:${RESET} $INSTALL_DIR"
    echo
    DC ps
    echo
    # Show disk usage
    DU=$(du -sh "$INSTALL_DIR" 2>/dev/null | cut -f1)
    echo -e "${BOLD}Disk usage:${RESET} $DU"

    # Show DB size if the app container exists
    APP_CID=$(app_container_id)
    DB_TMP=
    if [[ -n "${APP_CID:-}" ]]; then
        DB_TMP=$(mktemp)
        if docker cp "${APP_CID}:/app/data/app.db" "$DB_TMP" >/dev/null 2>&1; then
            DB_SIZE=$(du -sh "$DB_TMP" | cut -f1)
        fi
        rm -f "$DB_TMP"
    fi
    if [[ -n "${DB_SIZE:-}" ]]; then
        echo -e "${BOLD}Database:${RESET} $DB_SIZE"
    fi

    # Show nginx log sizes
    LOGS_DIR="$INSTALL_DIR/nginx/logs"
    if [[ -d "$LOGS_DIR" ]]; then
        echo -e "${BOLD}Nginx logs:${RESET}"
        for f in "$LOGS_DIR"/*.log; do
            [[ -f "$f" ]] || continue
            printf "  %-30s %s\n" "$(basename "$f")" "$(du -sh "$f" | cut -f1)"
        done 2>/dev/null
    fi
}

# ── Backup ────────────────────────────────────────────────────────────────────
cmd_backup() {
    header "Backup"

    TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
    BACKUP_FILE="${HOME}/singbox-backup_${TIMESTAMP}.zip"
    TMP_DIR=$(mktemp -d)
    trap 'rm -rf "$TMP_DIR"' RETURN

    info "Creating backup at: $BACKUP_FILE"

    mkdir -p \
        "$TMP_DIR/config/sing-box" \
        "$TMP_DIR/config/adguard" \
        "$TMP_DIR/data" \
        "$TMP_DIR/nginx/conf.d" \
        "$TMP_DIR/nginx/htpasswd"

    [[ -f "$INSTALL_DIR/.env" ]] && cp "$INSTALL_DIR/.env" "$TMP_DIR/.env"
    [[ -f "$INSTALL_DIR/config/sing-box/config.json" ]] && cp "$INSTALL_DIR/config/sing-box/config.json" "$TMP_DIR/config/sing-box/config.json"
    [[ -f "$INSTALL_DIR/config/adguard/AdGuardHome.yaml" ]] && cp "$INSTALL_DIR/config/adguard/AdGuardHome.yaml" "$TMP_DIR/config/adguard/AdGuardHome.yaml"
    [[ -f "$INSTALL_DIR/data/adguard_admin_password" ]] && cp "$INSTALL_DIR/data/adguard_admin_password" "$TMP_DIR/data/adguard_admin_password"
    [[ -f "$INSTALL_DIR/data/ssh_port" ]] && cp "$INSTALL_DIR/data/ssh_port" "$TMP_DIR/data/ssh_port"
    [[ -f "$INSTALL_DIR/nginx/.banned_ips.json" ]] && cp "$INSTALL_DIR/nginx/.banned_ips.json" "$TMP_DIR/nginx/.banned_ips.json"
    [[ -f "$INSTALL_DIR/nginx/.site_enabled" ]] && cp "$INSTALL_DIR/nginx/.site_enabled" "$TMP_DIR/nginx/.site_enabled"
    [[ -f "$INSTALL_DIR/nginx/conf.d/singbox.conf" ]] && cp "$INSTALL_DIR/nginx/conf.d/singbox.conf" "$TMP_DIR/nginx/conf.d/singbox.conf"
    [[ -f "$INSTALL_DIR/nginx/htpasswd/.htpasswd" ]] && cp "$INSTALL_DIR/nginx/htpasswd/.htpasswd" "$TMP_DIR/nginx/htpasswd/.htpasswd"

    if [[ -d "$INSTALL_DIR/nginx/override" ]] && find "$INSTALL_DIR/nginx/override" -mindepth 1 -print -quit | grep -q .; then
        mkdir -p "$TMP_DIR/nginx/override"
        cp -a "$INSTALL_DIR/nginx/override/." "$TMP_DIR/nginx/override/"
    fi

    if [[ -d "$INSTALL_DIR/nginx/certs" ]] && find "$INSTALL_DIR/nginx/certs" -mindepth 1 -print -quit | grep -q .; then
        mkdir -p "$TMP_DIR/nginx/certs"
        cp -a "$INSTALL_DIR/nginx/certs/." "$TMP_DIR/nginx/certs/"
    fi

    APP_CID=$(app_container_id)
    if [[ -n "${APP_CID:-}" ]]; then
        DB_CONTAINER_TMP="/tmp/singbox-ui-bot-backup-$$.db"
        if docker exec "$APP_CID" python -c "import sqlite3; src = sqlite3.connect('file:/app/data/app.db?mode=ro', uri=True); dst = sqlite3.connect('$DB_CONTAINER_TMP'); src.backup(dst); dst.close(); src.close()" >/dev/null 2>&1; then
            docker cp "${APP_CID}:${DB_CONTAINER_TMP}" "$TMP_DIR/data/app.db" >/dev/null 2>&1 || true
            docker exec "$APP_CID" rm -f "$DB_CONTAINER_TMP" >/dev/null 2>&1 || true
        else
            docker cp "${APP_CID}:/app/data/app.db" "$TMP_DIR/data/app.db" >/dev/null 2>&1 || true
        fi
    fi

    cat > "$TMP_DIR/RESTORE.txt" <<'EOF'
singbox-ui-bot restore workflow

1. Install singbox-ui-bot on the new server first.
2. Copy this ZIP to the new server.
3. Run: singbox-ui-bot restore /path/to/backup.zip
4. The CLI will restore .env, config, DB, AdGuard state, and Nginx state.

If you changed the SSH port before, review sshd first and then run:
  singbox-ui-bot firewall
EOF

    if [[ ! -f "$TMP_DIR/.env" || ! -f "$TMP_DIR/config/sing-box/config.json" || ! -f "$TMP_DIR/data/app.db" ]]; then
        warn "Backup is missing one of the required recovery files (.env, config/sing-box/config.json, data/app.db)"
        return 1
    fi

    FILE_LIST=$(cd "$TMP_DIR" && find . -type f | sed 's#^\./##' | sort)
    MANIFEST_PATH="$TMP_DIR/manifest.json"
    {
        echo "{"
        echo '  "format": "singbox-ui-bot-backup-v2",'
        printf '  "created_at": "%s",\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo '  "entries": ['
        FIRST=1
        while IFS= read -r ITEM; do
            [[ -z "$ITEM" ]] && continue
            if [[ $FIRST -eq 0 ]]; then
                echo ","
            fi
            FIRST=0
            printf '    "%s"' "$ITEM"
        done <<< "$FILE_LIST"
        echo
        echo "  ]"
        echo "}"
    } > "$MANIFEST_PATH"

    if command -v zip &>/dev/null; then
        (
            cd "$TMP_DIR"
            zip -qr "$BACKUP_FILE" .
        )
    else
        python3 - "$TMP_DIR" "$BACKUP_FILE" <<'PYEOF'
import os
import sys
import zipfile

src_root = sys.argv[1]
out_path = sys.argv[2]

with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, _, files in os.walk(src_root):
        for name in files:
            full = os.path.join(root, name)
            arc = os.path.relpath(full, src_root)
            zf.write(full, arc)
PYEOF
    fi

    SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
    success "Backup created: $BACKUP_FILE ($SIZE)"
    echo
    echo -e "${BOLD}Contents:${RESET}"
    while IFS= read -r ITEM; do
        [[ -n "$ITEM" ]] && echo "  - $ITEM"
    done <<< "$(cd "$TMP_DIR" && find . -type f | sed 's#^\./##' | sort)"
    return 0

    # Files to include
    FILES=()
    [[ -f "$INSTALL_DIR/config/sing-box/config.json" ]] && FILES+=("$INSTALL_DIR/config/sing-box/config.json")
    [[ -f "$INSTALL_DIR/.env"                        ]] && FILES+=("$INSTALL_DIR/.env")

    APP_CID=$(app_container_id)
    if [[ -n "${APP_CID:-}" ]] && docker cp "${APP_CID}:/app/data/app.db" "$TMP_DIR/app.db" >/dev/null 2>&1; then
        FILES+=("$TMP_DIR/app.db")
    fi

    if [[ ${#FILES[@]} -eq 0 ]]; then
        warn "No backup files found (config.json, app.db, .env)"
        return 1
    fi

    # Create zip (use python3 as fallback if zip not available)
    if command -v zip &>/dev/null; then
        zip -j "$BACKUP_FILE" "${FILES[@]}" > /dev/null
    else
        python3 - "${FILES[@]}" "$BACKUP_FILE" <<'PYEOF'
import sys, zipfile, os
files = sys.argv[1:-1]
out   = sys.argv[-1]
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in files:
        zf.write(f, os.path.basename(f))
PYEOF
    fi

    SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
    success "Backup created: $BACKUP_FILE ($SIZE)"
    echo
    echo -e "${BOLD}Contents:${RESET}"
    for f in "${FILES[@]}"; do
        echo "  • $(basename "$f")"
    done
}

# ── Logs ──────────────────────────────────────────────────────────────────────
extract_backup_zip() {
    local backup_file="$1"
    local output_dir="$2"

    if command -v unzip &>/dev/null; then
        unzip -oq "$backup_file" -d "$output_dir" >/dev/null
    else
        python3 - "$backup_file" "$output_dir" <<'PYEOF'
import sys
import zipfile

backup_file = sys.argv[1]
output_dir = sys.argv[2]

with zipfile.ZipFile(backup_file, "r") as zf:
    zf.extractall(output_dir)
PYEOF
    fi
}

cmd_restore() {
    header "Restore"

    BACKUP_SOURCE="${1:-}"
    if [[ -z "${BACKUP_SOURCE:-}" ]]; then
        read -rp "Path to backup ZIP: " BACKUP_SOURCE
    fi

    if [[ ! -f "${BACKUP_SOURCE:-}" ]]; then
        error "Backup file not found: ${BACKUP_SOURCE:-<empty>}"
        return 1
    fi

    TMP_DIR=$(mktemp -d)
    trap 'rm -rf "$TMP_DIR"' RETURN

    info "Extracting backup..."
    extract_backup_zip "$BACKUP_SOURCE" "$TMP_DIR"

    if [[ ! -f "$TMP_DIR/.env" || ! -f "$TMP_DIR/config/sing-box/config.json" || ! -f "$TMP_DIR/data/app.db" ]]; then
        error "Unsupported backup format. Expected .env, config/sing-box/config.json, and data/app.db."
        return 1
    fi

    read -rp "Create a safety backup before restore? [Y/n]: " DO_BACKUP
    if [[ "$DO_BACKUP" != [nN] ]]; then
        cmd_backup || warn "Safety backup failed, continuing anyway..."
        echo
    fi

    read -rp "This will overwrite the current server state. Continue? [y/N]: " CONFIRM
    [[ "$CONFIRM" != [yY] ]] && { info "Restore cancelled."; return 0; }

    info "Restoring host files..."
    mkdir -p \
        "$INSTALL_DIR/config/sing-box" \
        "$INSTALL_DIR/config/adguard" \
        "$INSTALL_DIR/data" \
        "$INSTALL_DIR/nginx/conf.d" \
        "$INSTALL_DIR/nginx/override" \
        "$INSTALL_DIR/nginx/htpasswd" \
        "$INSTALL_DIR/nginx/certs"

    cp "$TMP_DIR/.env" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    cp "$TMP_DIR/config/sing-box/config.json" "$INSTALL_DIR/config/sing-box/config.json"

    [[ -f "$TMP_DIR/config/adguard/AdGuardHome.yaml" ]] && cp "$TMP_DIR/config/adguard/AdGuardHome.yaml" "$INSTALL_DIR/config/adguard/AdGuardHome.yaml"
    [[ -f "$TMP_DIR/data/adguard_admin_password" ]] && cp "$TMP_DIR/data/adguard_admin_password" "$INSTALL_DIR/data/adguard_admin_password"
    [[ -f "$TMP_DIR/data/ssh_port" ]] && cp "$TMP_DIR/data/ssh_port" "$INSTALL_DIR/data/ssh_port"
    if [[ -f "$TMP_DIR/nginx/.banned_ips.json" ]]; then
        cp "$TMP_DIR/nginx/.banned_ips.json" "$INSTALL_DIR/nginx/.banned_ips.json"
    else
        rm -f "$INSTALL_DIR/nginx/.banned_ips.json"
    fi
    [[ -f "$TMP_DIR/nginx/conf.d/singbox.conf" ]] && cp "$TMP_DIR/nginx/conf.d/singbox.conf" "$INSTALL_DIR/nginx/conf.d/singbox.conf"
    [[ -f "$TMP_DIR/nginx/htpasswd/.htpasswd" ]] && cp "$TMP_DIR/nginx/htpasswd/.htpasswd" "$INSTALL_DIR/nginx/htpasswd/.htpasswd"

    if [[ -f "$TMP_DIR/nginx/.site_enabled" ]]; then
        cp "$TMP_DIR/nginx/.site_enabled" "$INSTALL_DIR/nginx/.site_enabled"
    else
        rm -f "$INSTALL_DIR/nginx/.site_enabled"
    fi

    rm -rf "$INSTALL_DIR/nginx/override"
    mkdir -p "$INSTALL_DIR/nginx/override"
    if [[ -d "$TMP_DIR/nginx/override" ]]; then
        cp -a "$TMP_DIR/nginx/override/." "$INSTALL_DIR/nginx/override/"
    fi

    rm -rf "$INSTALL_DIR/nginx/certs"
    mkdir -p "$INSTALL_DIR/nginx/certs"
    if [[ -d "$TMP_DIR/nginx/certs" ]]; then
        cp -a "$TMP_DIR/nginx/certs/." "$INSTALL_DIR/nginx/certs/"
    fi

    info "Recreating containers to apply restored environment..."
    DC up -d --force-recreate app singbox nginx adguard

    APP_CID=$(app_container_id)
    if [[ -z "${APP_CID:-}" ]]; then
        error "App container is not running after restore."
        return 1
    fi

    info "Restoring SQLite database into the app volume..."
    docker cp "$TMP_DIR/data/app.db" "${APP_CID}:/app/data/app.db"

    info "Restarting the stack..."
    DC restart app singbox nginx adguard

    success "Restore complete."
    echo
    echo "Next steps:"
    echo "  - Verify the bot and web UI can log in"
    echo "  - If SSH port was customized before, run: singbox-ui-bot firewall"
}

cmd_logs() {
    header "Logs"
    echo "Which container?"
    echo "  1) app (bot + API)"
    echo "  2) singbox"
    echo "  3) nginx"
    echo "  4) adguard"
    echo "  5) All (interleaved)"
    echo
    read -rp "Choice [1-5]: " CHOICE

    case "$CHOICE" in
        1) DC logs --tail=100 -f app ;;
        2) DC logs --tail=100 -f singbox ;;
        3) DC logs --tail=100 -f nginx ;;
        4) DC logs --tail=100 -f adguard ;;
        5) DC logs --tail=100 -f ;;
        *) warn "Invalid choice" ;;
    esac
}

# ── Restart ───────────────────────────────────────────────────────────────────
cmd_restart() {
    header "Restart"
    echo "What to restart?"
    echo "  1) All containers (recommended)"
    echo "  2) app only (bot + API)"
    echo "  3) singbox only"
    echo "  4) nginx only"
    echo
    read -rp "Choice [1-4]: " CHOICE

    case "$CHOICE" in
        1)
            info "Restarting all containers…"
            DC restart
            success "All containers restarted"
            ;;
        2) DC restart app;     success "app restarted" ;;
        3) DC restart singbox; success "singbox restarted" ;;
        4) DC restart nginx;   success "nginx restarted" ;;
        *) warn "Invalid choice" ;;
    esac
}

# ── Update ────────────────────────────────────────────────────────────────────
cmd_update() {
    header "Update"
    warn "This will pull the latest code from GitHub and rebuild the app container."
    warn "Your data (config.json, app.db, .env) will NOT be affected."
    echo
    read -rp "Continue? [y/N]: " CONFIRM
    [[ "$CONFIRM" != [yY] ]] && { info "Update cancelled."; return; }

    info "Creating backup before update…"
    cmd_backup

    info "Pulling latest changes…"
    git pull origin main || { error "git pull failed. Check your internet connection."; return 1; }

    info "Rebuilding app container…"
    DC build app

    info "Restarting app container…"
    DC up -d app

    success "Update complete!"
}

# ── Clear logs ────────────────────────────────────────────────────────────────
cmd_clear_logs() {
    header "Clear Nginx Logs"
    LOGS_DIR="$INSTALL_DIR/nginx/logs"

    if [[ ! -d "$LOGS_DIR" ]]; then
        warn "Logs directory not found: $LOGS_DIR"
        return
    fi

    echo "Log files:"
    for f in "$LOGS_DIR"/*.log 2>/dev/null; do
        [[ -f "$f" ]] && printf "  %-30s %s\n" "$(basename "$f")" "$(du -sh "$f" | cut -f1)"
    done
    echo
    read -rp "Clear all logs? [y/N]: " CONFIRM
    [[ "$CONFIRM" != [yY] ]] && { info "Cancelled."; return; }

    for f in "$LOGS_DIR"/*.log 2>/dev/null; do
        [[ -f "$f" ]] && > "$f" && echo "  Cleared: $(basename "$f")"
    done
    success "All logs cleared"
}

# ── Uninstall ─────────────────────────────────────────────────────────────────
cmd_uninstall() {
    header "Uninstall"

    echo -e "${RED}${BOLD}WARNING: This will PERMANENTLY delete all data!${RESET}"
    echo
    echo "The following will be removed:"
    echo "  • All running containers (app, singbox, nginx, adguard)"
    echo "  • Docker images used by this project"
    echo "  • Installation directory: $INSTALL_DIR"
    echo "  • This management script: /usr/local/bin/singbox-ui-bot"
    echo
    echo -e "${YELLOW}Crontab entries for SSL renewal will also be removed.${RESET}"
    echo

    # First, offer a backup
    read -rp "Create a backup before uninstalling? [Y/n]: " DO_BACKUP
    if [[ "$DO_BACKUP" != [nN] ]]; then
        cmd_backup || warn "Backup failed, continuing anyway…"
        echo
    fi

    echo -e "${RED}${BOLD}Last chance! Type 'yes' to confirm complete uninstall:${RESET} "
    read -r FINAL_CONFIRM
    if [[ "$FINAL_CONFIRM" != "yes" ]]; then
        info "Uninstall cancelled."
        return
    fi

    info "Stopping and removing containers…"
    DC down --volumes --remove-orphans 2>/dev/null || true

    info "Removing Docker images…"
    # Remove images built by this project
    docker rmi "$(DC images -q)" 2>/dev/null || true
    # Remove singbox-ui-bot-app image specifically
    docker rmi singbox-ui-bot-app 2>/dev/null || true

    info "Removing crontab entries…"
    (crontab -l 2>/dev/null | grep -v "singbox-ui-bot\|certbot" | crontab -) 2>/dev/null || true

    info "Removing installation directory…"
    rm -rf "$INSTALL_DIR"

    info "Removing management script…"
    rm -f /usr/local/bin/singbox-ui-bot

    echo
    success "Uninstall complete. The server has been cleaned."
    echo -e "${CYAN}If you had a backup, it is saved at: ~/singbox-backup_*.zip${RESET}"
    echo
    # Script about to delete itself — exit cleanly
    exit 0
}

# ── Main menu ─────────────────────────────────────────────────────────────────
show_menu() {
    echo
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${CYAN}║      singbox-ui-bot  CLI         ║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════╝${RESET}"
    echo
    echo -e "  ${BOLD}1)${RESET} 📊 Status"
    echo -e "  ${BOLD}2)${RESET} 💾 Backup"
    echo -e "  ${BOLD}3)${RESET} 📋 Logs"
    echo -e "  ${BOLD}4)${RESET} 🔄 Restart"
    echo -e "  ${BOLD}5)${RESET} ⬆️  Update"
    echo -e "  ${BOLD}6)${RESET} 🧹 Clear logs"
    echo -e "  ${BOLD}7)${RESET} 🔐 Apply firewall (SSH port from bot)"
    echo -e "  ${BOLD}8)${RESET} 🗑  Uninstall (cleanup server)"
    echo -e "  ${BOLD}0)${RESET} Exit"
    echo
}

main() {
    # Handle direct subcommands (non-interactive)
    if [[ $# -gt 0 ]]; then
        case "$1" in
            status)    cmd_status ;;
            backup)    cmd_backup ;;
            restore)   shift; cmd_restore "${1:-}" ;;
            logs)      cmd_logs ;;
            restart)   cmd_restart ;;
            update)    cmd_update ;;
            firewall)  cmd_firewall ;;
            uninstall) cmd_uninstall ;;
            *)
                error "Unknown command: $1"
                echo "Usage: singbox-ui-bot [status|backup|restore <backup.zip>|logs|restart|update|firewall|uninstall]"
                exit 1
                ;;
        esac
        exit 0
    fi

    # Interactive mode
    while true; do
        show_menu
        read -rp "Choose an option: " CHOICE
        case "$CHOICE" in
            1) cmd_status ;;
            2) cmd_backup ;;
            3) cmd_logs ;;
            4) cmd_restart ;;
            5) cmd_update ;;
            6) cmd_clear_logs ;;
            7) cmd_firewall ;;
            8) cmd_uninstall ;;
            0) echo; info "Bye!"; exit 0 ;;
            *) warn "Invalid option: $CHOICE" ;;
        esac
        echo
        read -rp "Press Enter to return to menu…" _
    done
}

main "$@"
