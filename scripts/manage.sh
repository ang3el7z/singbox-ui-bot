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

    # Show DB size if exists
    DB="$INSTALL_DIR/data/app.db"
    if [[ -f "$DB" ]]; then
        DB_SIZE=$(du -sh "$DB" | cut -f1)
        echo -e "${BOLD}Database:${RESET} $DB_SIZE"
    fi

    # Show nginx log sizes
    LOGS_DIR="$INSTALL_DIR/nginx/logs"
    if [[ -d "$LOGS_DIR" ]]; then
        echo -e "${BOLD}Nginx logs:${RESET}"
        for f in "$LOGS_DIR"/*.log 2>/dev/null; do
            [[ -f "$f" ]] && printf "  %-30s %s\n" "$(basename "$f")" "$(du -sh "$f" | cut -f1)"
        done
    fi
}

# ── Backup ────────────────────────────────────────────────────────────────────
cmd_backup() {
    header "Backup"

    TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
    BACKUP_FILE="${HOME}/singbox-backup_${TIMESTAMP}.zip"

    info "Creating backup at: $BACKUP_FILE"

    # Files to include
    FILES=()
    [[ -f "$INSTALL_DIR/config/sing-box/config.json" ]] && FILES+=("$INSTALL_DIR/config/sing-box/config.json")
    [[ -f "$INSTALL_DIR/data/app.db"                ]] && FILES+=("$INSTALL_DIR/data/app.db")
    [[ -f "$INSTALL_DIR/.env"                        ]] && FILES+=("$INSTALL_DIR/.env")

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
            logs)      cmd_logs ;;
            restart)   cmd_restart ;;
            update)    cmd_update ;;
            firewall)  cmd_firewall ;;
            uninstall) cmd_uninstall ;;
            *)
                error "Unknown command: $1"
                echo "Usage: singbox-ui-bot [status|backup|logs|restart|update|firewall|uninstall]"
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
