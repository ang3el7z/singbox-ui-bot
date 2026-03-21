# Quick Start

Minimum path from empty install to a working client.

## 1. Create inbound

Menu: `Inbounds -> Add`

Recommended start:

- protocol: `vless_reality`
- port: `443`
- tag: readable name, for example `main-reality`

## 2. Add client

Menu: `Clients -> Add Client`

Set:

- client name
- inbound from step 1
- traffic limit (optional)
- expiration (optional)

## 3. Deliver config to user

In client card:

- `Sub URL` — subscription link
- `Download config` — JSON file

## 4. Verify connection

- import profile in client app
- open a website
- confirm traffic counters change in client stats

## 5. Baseline security

- do not share UUID/password in public chats
- disable unused clients instead of leaving them active
- review `Audit log` regularly

## 6. Same-day tasks

- set scheduled backups
- set scheduled log cleanup
- set correct `ssh_port` in Settings and apply host firewall
