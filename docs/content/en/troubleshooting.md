# Troubleshooting

Common symptoms and practical recovery order.

## Symptom: `🔴 Sing-Box: stopped`

Meaning:

- Sing-Box container is not running
- `reload` usually fails while service is down

Check order:

1. Open `Sing-Box -> Logs`
2. If logs are empty, run `Restart`
3. Re-check `Status`
4. If it stops again, validate your latest config change

## Symptom: `Reload failed`

Typical reasons:

- service is already stopped
- syntax error in `config.json`
- container cannot read config path or file

Fix:

1. Start service with `Restart`
2. Run `Reload` only after it is healthy
3. If error repeats, restore last working backup

## Symptom: Logs button shows nothing

Possible reasons:

- container is down and has no fresh logs
- temporary API timeout
- stale callback from old menu message

What to do:

1. Refresh menu
2. Check `Status`
3. Run `Restart`
4. Open `Logs` again

If still broken:

- open `Maintenance -> Logs`
- download related log file for offline review

## After bad routing/inbound change

Safe sequence:

1. Revert latest change
2. Run `Reload`
3. If not recovered, `Restore` from backup

## Failure after update

1. Read `Maintenance -> Update logs`
2. Verify all containers are running
3. Restore from latest stable backup if needed

## When restore is the right first move

- service does not start after multiple attempts
- config is corrupted and fast recovery matters more than root cause analysis
- production users are already impacted
