# Daily Operations

Short reference for each panel section.

## Sing-Box

- `Status` — container runtime state
- `Reload` — re-read config without full restart
- `Restart` — full container restart
- `Logs` — recent core logs

## Clients

- create and delete profiles
- enable/disable client
- reset traffic stats
- provide subscription URL and JSON config

## Inbounds

- add inbound endpoints for different protocols
- remove inbound carefully (affects assigned clients)

## Routing

- rules by domain, suffix, keyword, ip_cidr
- action targets: `proxy`, `direct`, `block`, `dns`
- import/export rule sets

## AdGuard

- DNS protection status
- upstream DNS management
- filter rules
- client sync

## Nginx

- config generation and apply
- SSL issuance
- hidden paths and access logs
- public stub/site management

## Settings

- `domain`
- `tz`
- `bot_lang`
- `ssh_port` for host firewall script

## Maintenance

- backup / restore
- log management and rotation
- IP ban workflows
- update and reinstall flows
