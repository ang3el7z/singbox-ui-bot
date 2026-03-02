# REST API Reference

Base URL: `https://vpn.example.com`

Interactive docs available at: `/api/docs` (Swagger UI)

---

## Authentication

Two methods:

| Method | Header | Used by |
|--------|--------|---------|
| JWT Bearer | `Authorization: Bearer <token>` | Web UI |
| Internal Token | `X-Internal-Token: <token>` | Telegram bot (same process) |

### Login (Web UI)

```http
POST /api/auth/login
Content-Type: application/json

{"username": "admin", "password": "changeme"}
```

Response:
```json
{"access_token": "eyJ...", "token_type": "bearer", "username": "admin"}
```

Use the `access_token` in subsequent requests:
```
Authorization: Bearer eyJ...
```

---

## Server

```
GET  /api/server/status   — Sing-Box running status
GET  /api/server/logs     — Recent logs (?lines=100)
POST /api/server/restart  — Restart container
POST /api/server/reload   — Reload config (graceful)
GET  /api/server/config   — Full config.json (raw)
GET  /api/server/keypair  — Generate Reality keypair
```

---

## Clients

```
GET    /api/clients/            — List all clients
POST   /api/clients/            — Create client
GET    /api/clients/{id}        — Get client
PATCH  /api/clients/{id}        — Update (enable, total_gb, expire_days)
DELETE /api/clients/{id}        — Delete client
POST   /api/clients/{id}/reset-stats   — Reset traffic counters
GET    /api/clients/{id}/subscription  — Client-side config.json
```

### Create Client

```http
POST /api/clients/
Content-Type: application/json

{
  "name": "John",
  "inbound_tag": "vless-in",
  "total_gb": 50,
  "expire_days": 30
}
```

---

## Inbounds

```
GET    /api/inbounds/       — List (from config.json)
POST   /api/inbounds/       — Create inbound
GET    /api/inbounds/{tag}  — Get inbound
PATCH  /api/inbounds/{tag}  — Update fields
DELETE /api/inbounds/{tag}  — Delete inbound
```

Supported protocols: `vless_reality`, `vless_ws`, `vmess_ws`, `trojan`, `shadowsocks`, `hysteria2`, `tuic`

---

## Routing Rules

```
GET    /api/routing/               — Full route section
GET    /api/routing/rules/{key}    — Rules by type
POST   /api/routing/rules          — Add rule
DELETE /api/routing/rules          — Delete rule (?rule_key=domain&value=example.com)
POST   /api/routing/rule-sets      — Add rule set
DELETE /api/routing/rule-sets/{tag}— Delete rule set
GET    /api/routing/export         — Export rules JSON
POST   /api/routing/import         — Import rules JSON
```

Rule keys: `domain`, `domain_suffix`, `domain_keyword`, `ip_cidr`, `geosite`, `geoip`, `rule_set`

Outbound values: `proxy`, `direct`, `block`, `dns`

---

## AdGuard

```
GET  /api/adguard/status           — Protection status + availability
GET  /api/adguard/stats            — 24h statistics
POST /api/adguard/protection       — Toggle (?enabled=true|false)
GET  /api/adguard/dns              — DNS info
POST /api/adguard/dns/upstream     — Add upstream DNS
DEL  /api/adguard/dns/upstream     — Remove upstream (?upstream=8.8.8.8)
GET  /api/adguard/rules            — Filter rules
POST /api/adguard/rules            — Add filter rule
DEL  /api/adguard/rules            — Remove rule (?rule=||example.com^)
POST /api/adguard/password         — Change AG password
POST /api/adguard/sync-clients     — Sync SB clients → AG
```

---

## Nginx

```
GET  /api/nginx/status             — Override status + hidden paths
POST /api/nginx/configure          — Generate config + reload
POST /api/nginx/ssl                — Issue SSL certificate
GET  /api/nginx/paths              — Hidden panel paths
GET  /api/nginx/logs               — Access logs (?lines=50)
POST /api/nginx/override/upload    — Upload HTML or ZIP (multipart file)
DEL  /api/nginx/override           — Remove custom site
GET  /api/nginx/override/status    — Current override status
```

---

## Federation

```
GET    /api/federation/            — List nodes
POST   /api/federation/            — Add node
GET    /api/federation/{id}        — Get node
DELETE /api/federation/{id}        — Delete node
POST   /api/federation/{id}/ping   — Ping node
POST   /api/federation/ping-all    — Ping all nodes
POST   /api/federation/bridge      — Create bridge chain ({"node_ids": [1,2]})
GET    /api/federation/topology    — Network topology
```

### Federation HMAC Endpoints (server-to-server)

These are public but authenticated via HMAC-SHA256 signature:

```
GET  /federation/info          — Node info
POST /federation/ping          — Signed ping
POST /federation/inbounds      — Get inbounds (signed)
POST /federation/add_outbound  — Add outbound to this node (signed)
```

---

## Admin

```
GET    /api/admin/admins              — List Telegram admins
POST   /api/admin/admins              — Add admin ({"telegram_id": 123456})
DELETE /api/admin/admins/{telegram_id}— Remove admin
GET    /api/admin/audit-log           — Audit log (?limit=50)
GET    /api/admin/backup              — Download backup ZIP
```

---

## Health Check

```
GET /health → {"status": "ok", "version": "2.0.0"}
```
