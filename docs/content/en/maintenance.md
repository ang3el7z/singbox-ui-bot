# Maintenance

Operational section for backup, logs, and updates.

## Backup

Recommended policy:

- scheduled backup every 6-24 hours
- mandatory backup before updates
- at least one off-server copy

### Typical backup payload

- `.env`
- `config/sing-box/config.json`
- `data/app.db`
- Nginx and AdGuard state

## Restore

Use when you need fast return to stable state.

Before restore:

1. Create safety backup if possible
2. Confirm you selected the correct archive

After restore:

1. Check all container statuses
2. Verify Web UI and Telegram operations
3. Verify client connectivity

## Logs

Good practice:

- download logs before clearing during incidents
- keep auto-clean enabled
- avoid clearing all logs while active troubleshooting is ongoing

## IP Ban

Use for:

- manual blocking of noisy IPs
- batch ban after log analysis

Review bans regularly to avoid false positives.

## Updates

Safe sequence:

1. Backup
2. Update
3. Status check
4. Smoke test key scenarios (client create, sub URL, DNS)

If update fails:

- inspect update logs
- restore last stable backup
