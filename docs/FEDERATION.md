# Federation Guide

Federation allows connecting multiple Singbox UI Bot instances to build multi-hop VPN chains or use remote servers as exit nodes.

## Concepts

| Term | Description |
|------|-------------|
| **Master** | Your main server that runs the bot |
| **Node** | A remote server also running Singbox UI Bot |
| **Bridge** | A chain: client → master → node1 → nodeN → Internet |

---

## Requirements

Both servers must:
- Run Singbox UI Bot v2+
- Have a domain with HTTPS (Let's Encrypt)
- Have `FEDERATION_SECRET` set (can be different on each server, you exchange them manually)

---

## Adding a Node

### Via Telegram Bot

1. `/menu` → **Federation** → **Add Node**
2. Enter node name (e.g. `node-amsterdam`)
3. Enter node URL: `https://node.example.com`
4. Enter the shared secret — must match `FEDERATION_SECRET` in the node's `.env`
5. Select role: **Node** (exit point) or **Bridge** (intermediate hop)

The bot will immediately try to ping the node and show online/offline status.

### Via Web UI

**Federation** section → **➕ Add Node** button.

---

## How Federation Works

When you ping a node, the master sends:
```json
{
  "timestamp": 1700000000,
  "hmac": "sha256_of(secret + timestamp + payload)"
}
```

The node verifies the HMAC and responds with its info.

When creating a bridge:
1. Master asks node for its inbounds
2. Master creates an outbound pointing to the node's inbound
3. The chain `client → master → node → Internet` is established automatically

---

## Security

- All federation API calls are signed with HMAC-SHA256
- Replay protection: requests older than 60 seconds are rejected
- Federation secret should be a strong random string (32+ chars)
- Keep each node's secret different from the master's main `FEDERATION_SECRET`
- HTTPS is required (enforced by TLS handshake before any data)

---

## Example: Building a Bridge

You have:
- Master: `vpn1.example.com`
- Node: `vpn2.example.com`

Steps:
1. Add `vpn2.example.com` as a node (via bot or web UI)
2. Verify it shows 🟢 Online
3. Bot → **Federation** → select the node → **Create Bridge**
4. The master will add a chained outbound pointing through `vpn2`
5. Reload Sing-Box config

Clients connecting to `vpn1` will now exit through `vpn2`.

---

## Topology View

`/menu` → **Federation** → **Topology** shows a visual representation of your network:

```
🖥 vpn1.example.com (master)
  └─ 🟢 node-amsterdam [node] — https://vpn2.example.com
  └─ 🔴 node-frankfurt [bridge] — https://vpn3.example.com
```
