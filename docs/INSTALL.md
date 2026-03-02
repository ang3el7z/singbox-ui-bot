# Installation Guide

## Requirements

| Component | Version |
|-----------|---------|
| OS        | Ubuntu 22.04 / Debian 12 |
| Docker    | 24+ |
| Docker Compose | v2+ |
| Domain    | A-record pointed to server |
| Ports     | 80, 443, 53 (UDP/TCP) open in firewall |

---

## Quick Install (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

This script:
1. Installs Docker + Docker Compose
2. Clones the repo to `/opt/singbox-ui-bot`
3. Generates a `.env` file with secure random secrets
4. Starts all containers

---

## Manual Installation

### 1. Clone repository

```bash
git clone https://github.com/ang3el7z/singbox-ui-bot.git /opt/singbox-ui-bot
cd /opt/singbox-ui-bot
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env
```

Required fields in `.env`:

```env
BOT_TOKEN=1234567890:AAxxxxxx        # From @BotFather
ADMIN_IDS=123456789                  # Your Telegram user ID (comma-separated for multiple)
DOMAIN=vpn.example.com               # Your domain
EMAIL=admin@example.com              # For Let's Encrypt

# Change all secrets to random strings!
INTERNAL_TOKEN=<random 32+ chars>
JWT_SECRET=<random 32+ chars>
FEDERATION_SECRET=<random 32+ chars>
SECRET_KEY=<random 32+ chars>

WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=<strong password>
```

### 3. Set up Nginx configuration

```bash
# Run Nginx template generation (done automatically on first bot start)
# Or trigger via bot: /menu → Nginx → Configure & Reload
```

### 4. Start services

```bash
docker compose up -d
```

Check status:
```bash
docker compose ps
docker compose logs -f app
```

### 5. Issue SSL certificate

Send `/menu` to your bot → **Nginx** → **Issue SSL Certificate**

Or via CLI:
```bash
docker compose exec app certbot --nginx -d vpn.example.com -m admin@example.com --agree-tos -n
```

---

## First Steps After Installation

1. Send `/start` to your bot → verify it responds
2. Go to **Inbounds** → Add an inbound (e.g. VLESS Reality on port 443)
3. Go to **Clients** → Add a client → Download config
4. Import the JSON config into Sing-Box client app

### Web UI

Open `https://vpn.example.com/web/` in your browser.
- Login with `WEB_ADMIN_USER` / `WEB_ADMIN_PASSWORD` from `.env`
- Change password after first login via **Admin** section

---

## Updating

```bash
cd /opt/singbox-ui-bot
bash scripts/update.sh
```

Or via bot: (future `/update` command)

---

## Directory Structure After Installation

```
/opt/singbox-ui-bot/
├── .env                    ← your configuration (never commit)
├── data/app.db             ← SQLite database
├── config/sing-box/
│   └── config.json         ← live Sing-Box config
├── nginx/
│   ├── conf.d/             ← generated Nginx config
│   ├── override/           ← optional custom stub site
│   └── htpasswd/           ← auto-generated htpasswd for 401 fallback
└── subs/                   ← client subscription configs
```

---

## Troubleshooting

**Bot doesn't respond:**
```bash
docker compose logs app --tail 50
```

**Sing-Box doesn't start:**
```bash
docker compose logs singbox --tail 50
```

**Nginx 502:**
- Ensure the `app` container is running on port 8080
- Check `docker compose ps`

**SSL certificate not issued:**
- Verify DNS A-record: `nslookup vpn.example.com`
- Ensure port 80 is open: `curl http://vpn.example.com`
