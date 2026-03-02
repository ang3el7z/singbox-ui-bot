# Singbox UI Bot

Telegram bot + Web UI for managing a [Sing-Box](https://github.com/SagerNet/sing-box) VPN server.

## System Requirements

| Component | Minimum |
|-----------|---------|
| OS | Ubuntu 22.04 / Debian 12 |
| CPU | 1 core |
| RAM | 512 MB |
| Disk | 10 GB |
| Docker | 24+ |
| Docker Compose | v2+ |
| Domain | A-record pointing to server IP |
| Open ports | 80, 443, 53 TCP+UDP |

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

The script will ask for your domain, email, Telegram bot token, and admin ID — then set everything up automatically.
