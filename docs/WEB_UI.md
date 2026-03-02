# Web UI Guide

The Web UI is a single-page application (Alpine.js + Tailwind CSS) that provides the same functionality as the Telegram bot, accessible via browser.

## Accessing the Web UI

After installation, navigate to:

```
https://vpn.example.com/web/
```

The path `/web/` is served through Nginx.

**Login credentials:**
- Username: `WEB_ADMIN_USER` from `.env` (default: `admin`)
- Password: `WEB_ADMIN_PASSWORD` from `.env`

> Change the default password immediately after first login!

---

## Sections

| Section | Description |
|---------|-------------|
| Dashboard | Overview: Sing-Box status, client count, inbound list |
| Server | Status, logs, restart/reload |
| Clients | Add, manage, download config, reset stats |
| Inbounds | Add/delete inbounds (VLESS Reality, Trojan, Hysteria2, etc.) |
| Routing | Manage routing rules (domain, IP, GeoSite, rule sets) |
| AdGuard | DNS protection, filter rules, upstream DNS |
| Nginx | Configure, SSL, upload custom site, view logs |
| Federation | Manage remote nodes, ping, create bridge chains |
| Admin | Telegram admin list, audit log, backup |

---

## Changing Web UI Password

Go to **Admin** section → **Change Password** button (or via API):

```http
POST /api/auth/change-password
Authorization: Bearer <your-token>

{"current_password": "oldpass", "new_password": "newpass"}
```

---

## JWT Session

- JWT tokens are stored in `localStorage`
- Default expiry: 7 days (configurable via `JWT_EXPIRE_MINUTES` in `.env`)
- On expiry, you're automatically redirected to login

---

## Hidden Panel Path

The web UI is served at `/web/`. This path is configured in Nginx by the app.

Other hidden paths (viewable via **Nginx → Hidden Paths**):
- `/sub/{sub_id}` — Client subscription config download
- `/adguard/` — AdGuard Home admin (proxied)
- `/api/` — REST API (requires auth)

---

## No-build Architecture

The Web UI requires no Node.js or npm. It uses:
- **Alpine.js** — reactive UI framework (CDN)
- **Tailwind CSS** — utility CSS (CDN)
- **ES modules** — native browser JS imports

All JavaScript is in `web/js/` and all styles in `web/css/style.css`.

---

## Customizing the Stub Site

The default behavior at `https://vpn.example.com/` is a **401 Basic Auth popup** — it looks like a protected website, not a VPN panel.

To replace it with a custom site:
1. **Web UI**: Nginx section → Upload HTML or ZIP
2. **Bot**: `/menu` → Nginx → Upload site (send HTML or ZIP file)

Upload requirements:
- HTML file: any `.html` or `.htm` file
- ZIP archive: must contain `index.html` at the root
- Maximum size: 20 MB
