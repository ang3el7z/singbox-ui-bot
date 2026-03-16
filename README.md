# Singbox UI Bot

Telegram bot + Web UI for managing a `sing-box` server from one backend.

## What This Project Does

The product combines four parts:

- `api/` - FastAPI backend with the main business logic
- `bot/` - Telegram admin interface on `aiogram`
- `web/` - browser admin panel
- `config/` + `nginx/` - generated runtime config for `sing-box`, Nginx and AdGuard

The bot and web panel are thin clients. Both work through the same API and operate on the same data.

## Main Features

- create and manage `sing-box` inbounds
- create client profiles and issue subscription URLs
- build client configs from templates
- manage Nginx masking site and SSL
- integrate with AdGuard Home
- manage routing rules
- create backups, clear logs, maintain IP ban list
- connect remote nodes through federation / bridge logic

## Runtime Layout

The default Docker setup starts:

- `app` - FastAPI + Telegram bot
- `singbox` - network core
- `adguard` - DNS filtering
- `nginx` - public entrypoint on `80/443`

Persistent state lives in:

- SQLite metadata in the `app` container volume (`/app/data/app.db`)
- `config/sing-box/config.json` - live `sing-box` config
- `nginx/override/` - uploaded public site
- `nginx/logs/` - access and error logs

## Requirements

| Component | Minimum |
|-----------|---------|
| OS | Ubuntu 22.04 / Debian 12 |
| CPU | 1 core |
| RAM | 512 MB |
| Disk | 10 GB |
| Docker | 24+ |
| Docker Compose | v2+ |
| Open ports | 80, 443, 53 TCP+UDP |

## Install

Installation is non-interactive. Pass the Telegram bot token from `@BotFather`:

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash -s -- YOUR_BOT_TOKEN
```

## First Run

1. Start the bot and send `/start`.
2. Complete the setup wizard: language, timezone, domain.
3. Configure Nginx / issue SSL.
4. Create an inbound.
5. Create a client and get the subscription URL.

## Important Notes

- A valid domain must be configured before generating subscription URLs or Windows service packages.
- Client metadata is stored in SQLite, while the live transport config is stored in `config/sing-box/config.json`.
- AdGuard admin password is auto-seeded from `ADGUARD_PASSWORD` on first boot and later changes are persisted by the app.
- Uploaded `.zip` override sites are validated to reject unsafe paths and oversized unpacked archives.

## Useful Paths

- API docs: `/api/swagger`
- Web UI: `/web/`
- Healthcheck: `/health`
- Telegram webhook: `/webhook` with `X-Telegram-Bot-Api-Secret-Token` when webhook mode is enabled

## Project Status

The project is aimed at self-hosted production use, but it is infrastructure-heavy:

- Docker access is required from the app container
- Nginx / Certbot / AdGuard must all be reachable and healthy
- `sing-box` reload behavior depends on the runtime environment

Before public release, validate the whole flow on a real server:

- first-run setup
- create inbound
- create client
- fetch subscription
- Nginx SSL issuance
- AdGuard integration
