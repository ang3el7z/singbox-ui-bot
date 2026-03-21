# Singbox UI Bot

Unified Sing-Box management through Telegram and Web UI.

## What it is

`Singbox UI Bot` is a control system where:

- Telegram bot and Web UI drive the same backend
- backend stores state in SQLite and writes Sing-Box `config.json`
- changes are applied without manual JSON editing

## Why this helps

- Fast control from a phone via Telegram
- Backup access via Web UI if Telegram is unavailable
- Predictable config flow without manual server edits
- Centralized audit trail and maintenance

## High-level flow

1. Create an inbound
2. Add a client
3. System generates connection parameters
4. Sing-Box reloads config
5. Client receives a working subscription URL

## Components

- `bot/` — Telegram interface
- `web/` — browser interface
- `api/` — business logic and REST
- `config/sing-box/config.json` — runtime config
- `data/app.db` — clients, settings, audit log

## Core principles

- Business logic lives in API, UI layers are thin clients
- Runtime settings (`domain`, `tz`, `bot_lang`, `ssh_port`) are stored in DB
- Always create a backup before major changes

## Next docs

- `Installation` — setup on a clean VPS
- `Quick Start` — first working profile in minutes
- `Troubleshooting` — fixes for common issues
