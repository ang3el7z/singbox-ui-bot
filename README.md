# Singbox UI Bot

Telegram bot + Web UI for managing a [Sing-Box](https://github.com/SagerNet/sing-box) server.

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

Installation is **non-interactive**: pass your Telegram bot token (from @BotFather) in the command:

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash -s -- YOUR_BOT_TOKEN
```

Or with env: `BOT_TOKEN=your_token bash install.sh`

Domain, language, and timezone are set in the bot on first `/start`.
