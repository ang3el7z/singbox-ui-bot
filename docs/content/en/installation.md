# Installation (Node-Only)

Install Singbox UI Bot on a single VPS with Docker.

## Before you start

- Ubuntu 22.04/24.04
- Root SSH access
- Domain pointed to your server IP
- Open ports `22`, `80`, `443`

## Step 1. Connect to the server

```bash
ssh root@YOUR_SERVER_IP
```

## Step 2. Run installer

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

The installer:

- installs Docker/Compose if needed
- starts service containers
- prepares config structure
- registers `singbox-ui-bot` CLI command

## Step 3. First run in Telegram

1. Open your bot
2. Run `/start`
3. Choose language and timezone
4. Set domain
5. Wait for initial setup to finish

## Step 4. Issue SSL

In `Nginx`, issue SSL and provide an email for Let's Encrypt.

After success:

- verify Web UI access
- verify API operations are healthy

## Step 5. Readiness check

Minimum checks:

1. `Sing-Box` status is `running`
2. Inbound creation succeeds
3. Client creation and subscription URL work
4. `Maintenance -> Backup` can produce archive

## Immediate hardening

- Change default Web UI password
- Configure scheduled backups
- Enable log cleanup schedule
- Store backup copies outside the server

## Fast rollback

If a change breaks the setup:

1. Open `Maintenance -> Backup`
2. Restore latest known-good archive
3. Restart services
