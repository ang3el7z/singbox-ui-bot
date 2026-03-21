# Federation

Link multiple servers into one routing network.

## When to use

- single node is overloaded
- you need multiple geo/provider exits
- you need fallback routing paths

## Basic setup path

1. Ensure each node has a healthy install
2. Verify domain and SSL on each node
3. Add remote nodes in `Federation`
4. Run `Ping all`
5. Build bridge chain if required

## Security

- inter-node auth uses shared secret
- never store secrets in public notes/chats
- rotate secret if compromise is suspected

## Practical tips

- start with 2 nodes, then scale
- keep node names explicit
- watch latency and availability via ping
- add routing rules only after stable connectivity

## Common failures

- mismatched shared secret
- wrong remote API URL
- domain/TLS misconfiguration
