# Singbox UI Bot

A Telegram bot + Web UI for managing [Sing-Box](https://github.com/SagerNet/sing-box) VPN servers.

No s-ui. No duplicate logic. One FastAPI backend, two thin clients.

```
┌──────────────┐   X-Internal-Token   ┌──────────────────────────────┐
│  Telegram    │──────────────────────▶│   api/ — FastAPI backend     │
│  bot/        │                       │   All business logic here     │
└──────────────┘                       │                              │
                                       │   ┌──────────────────────┐  │
┌──────────────┐   JWT Bearer          │   │ api/services/        │  │
│  Web UI      │──────────────────────▶│   │   singbox.py         │  │
│  web/        │                       │   │   adguard_api.py     │  │
└──────────────┘                       │   │   nginx_service.py   │  │
                                       │   │   federation_service │  │
                                       │   └──────────────────────┘  │
                                       └──────────────────────────────┘
                                                      │
                              ┌───────────────────────┼───────────────┐
                          config.json             AdGuard           Nginx
                          (Sing-Box)              REST API          templates
```

## Features

- 🖥 **Server**: Sing-Box status, logs, graceful reload, restart
- 👥 **Clients**: Add, delete, enable/disable, QR code, subscription config download
- 🔌 **Inbounds**: VLESS Reality/WS, VMess, Trojan, Shadowsocks, Hysteria2, TUIC
- 🗺 **Routing**: Domain/IP/GeoSite/GeoIP/RuleSet rules — add, delete, import/export
- 🛡 **AdGuard Home**: Protection toggle, DNS, filter rules, client sync
- 🌐 **Nginx**: Auto-configure, SSL (Let's Encrypt), custom stub site upload
- 🔗 **Federation**: Link multiple bot instances — bridge chains, topology view
- 👑 **Admin**: Multi-admin support, audit log, backup

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

See [docs/INSTALL.md](docs/INSTALL.md) for detailed instructions.

## Documentation

| Document | Description |
|----------|-------------|
| [INSTALL.md](docs/INSTALL.md) | Installation, configuration, troubleshooting |
| [API.md](docs/API.md) | Full REST API reference (all endpoints) |
| [FEDERATION.md](docs/FEDERATION.md) | Multi-node federation setup |
| [WEB_UI.md](docs/WEB_UI.md) | Web UI guide |

## Architecture

```
singbox-ui-bot/
├── api/                  ← FastAPI (all business logic)
│   ├── main.py           ← FastAPI app + lifespan
│   ├── config.py         ← pydantic-settings
│   ├── database.py       ← SQLAlchemy models
│   ├── deps.py           ← JWT + internal token auth
│   ├── routers/          ← REST endpoints
│   └── services/         ← singbox, adguard, nginx, federation
│
├── bot/                  ← Telegram bot (thin UI client)
│   ├── main.py           ← aiogram + uvicorn in same process
│   ├── api_client.py     ← HTTP client → /api/*
│   ├── handlers/         ← aiogram handlers (FSM, menus)
│   ├── keyboards/        ← InlineKeyboardMarkup builders
│   └── middleware/       ← auth, rate limit
│
├── web/                  ← Web UI (Alpine.js SPA, no build step)
│   ├── index.html        ← full SPA
│   ├── js/               ← api.js, app.js
│   └── css/              ← style.css
│
├── config/sing-box/      ← Sing-Box config + templates
├── nginx/                ← Nginx templates, generated configs, override
├── docs/                 ← documentation
└── docker-compose.yml    ← 4 services: app, singbox, adguard, nginx
```

## Stack

- **Python 3.11** — FastAPI 0.115 + aiogram 3.13 + SQLAlchemy 2.0 (async)
- **Database**: SQLite (aiosqlite)
- **VPN core**: Sing-Box (direct config.json management)
- **DNS**: AdGuard Home (REST API)
- **Reverse proxy**: Nginx (Jinja2 templates, auto-configure)
- **Auth**: JWT (web UI) + HMAC-SHA256 (federation)
- **Frontend**: Alpine.js 3 + Tailwind CSS (no build)
- **Containers**: Docker Compose

## License

MIT — see [LICENSE](LICENSE)

## Repository

https://github.com/ang3el7z/singbox-ui-bot
