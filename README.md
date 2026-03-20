# Requirements

| Component | Minimum |
|-----------|---------|
| OS | Ubuntu 22.04 / Debian 12 |
| CPU | 1 core |
| RAM | 512 MB |
| Disk | 10 GB |
| Docker | 24+ |
| Docker Compose | v2+ |
| Open ports | 80, 443, 53 TCP+UDP |

# Install

Installation is non-interactive. Pass the Telegram bot token from `@BotFather`:

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash -s -- YOUR_BOT_TOKEN
```

# Links

- Install: `scripts/install.sh`
- Web UI: `/web/`
- API docs: `/api/swagger`
- Healthcheck: `/health`
- Migrations policy: `docs/MIGRATIONS.md`
