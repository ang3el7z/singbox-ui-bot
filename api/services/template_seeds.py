"""
Built-in client subscription templates.

Each template is a full sing-box client config JSON where:
  • {"tag": "proxy", "type": "__proxy__"} — replaced with the real proxy outbound at subscription time.
  • "__dns_url__" in any DNS server address — replaced with the user's personal AdGuard DoH URL
    (https://{domain}/{doh_path}/{sub_id}), enabling per-user DNS filtering via AdGuard Home.

The __proxy__ placeholder MUST be present exactly once.

Architecture (mirrors vpnbot's sing.json):
  dns_adguard (DoH → server's AdGuard, filtered, detour=direct)
      └── address_resolver: dns_bootstrap (plain TCP 8.8.8.8, resolves AdGuard's hostname)
  All outbound queries → dns_adguard (via "outbound: any" rule)
  Result: ad-blocked DNS for all VPN users, queries visible in AdGuard per-client stats.
"""
import json

# ─── DNS block (injected into all non-fakeip templates) ────────────────────────────
# "__dns_url__" is replaced at build time with https://{domain}/{doh_hash}/{sub_id}
_DNS_ADGUARD = {
    "servers": [
        {
            "tag": "dns_adguard",
            "address": "__dns_url__",        # AdGuard DoH URL injected per-user at build time
            "address_resolver": "dns_bootstrap",
            "strategy": "prefer_ipv4",
            "detour": "direct",              # DNS queries bypass the VPN tunnel → go to server directly
        },
        {
            # Bootstrap: plain TCP to resolve the DoH server's hostname (avoid chicken-and-egg)
            "tag": "dns_bootstrap",
            "address": "tcp://8.8.8.8",
            "detour": "direct",
        },
    ],
    "rules": [
        # All outbound connections use AdGuard for DNS
        {"outbound": "any", "server": "dns_adguard", "disable_cache": False},
    ],
    "strategy": "ipv4_only",
    "final": "dns_adguard",
    "independent_cache": True,
}

# ─── Common route rules shared by most templates ─────────────────────────────────
_COMMON_RULES = [
    {"action": "sniff"},
    {"protocol": "dns", "action": "hijack-dns"},
    {"ip_is_private": True, "outbound": "direct"},
]

_COMMON_OUTBOUNDS = [
    {"tag": "proxy", "type": "__proxy__"},
    {"tag": "direct", "type": "direct"},
    {"tag": "block",  "type": "block"},
]

# ─── Template definitions ─────────────────────────────────────────────────────────

BUILTIN_TEMPLATES = [
    {
        "name": "tun",
        "label": "TUN — Phone / PC (Android, iOS, Linux, macOS)",
        "is_default": True,
        "config": {
            "log": {"level": "error", "timestamp": True},
            "dns": _DNS_ADGUARD,
            "inbounds": [{
                "type": "tun",
                "tag": "tun-in",
                "address": ["172.19.0.1/30"],
                "mtu": 1400,
                "auto_route": True,
                "strict_route": True,
                "sniff": True,
                "domain_strategy": "prefer_ipv4",
            }],
            "outbounds": _COMMON_OUTBOUNDS,
            "route": {
                "rules": _COMMON_RULES,
                "final": "proxy",
                "auto_detect_interface": True,
            },
            "experimental": {"cache_file": {"enabled": True}},
        },
    },
    {
        "name": "tun_fakeip",
        "label": "TUN + FakeIP — Phone / PC (faster DNS, advanced routing)",
        "is_default": False,
        "config": {
            "log": {"level": "error", "timestamp": True},
            "dns": {
                "servers": [
                    {
                        # DoH DNS via AdGuard (for direct/block outbounds)
                        "tag": "dns_adguard",
                        "address": "__dns_url__",
                        "address_resolver": "dns_bootstrap",
                        "strategy": "prefer_ipv4",
                        "detour": "direct",
                    },
                    {
                        "tag": "dns_bootstrap",
                        "address": "tcp://8.8.8.8",
                        "detour": "direct",
                    },
                    {
                        # FakeIP for proxy-bound traffic — faster routing decisions
                        "tag": "dns_fakeip",
                        "address": "fakeip",
                        "inet4_range": "198.18.0.0/15",
                        "inet6_range": "fc00::/18",
                    },
                ],
                "rules": [
                    # Outbound DNS resolution uses direct AdGuard
                    {"outbound": "any", "server": "dns_adguard", "disable_cache": False},
                    # A/AAAA queries for routing get fake IPs (domain sent to proxy for real resolution)
                    {"query_type": ["A", "AAAA"], "server": "dns_fakeip"},
                ],
                "strategy": "ipv4_only",
                "final": "dns_adguard",
                "independent_cache": True,
            },
            "inbounds": [{
                "type": "tun",
                "tag": "tun-in",
                "address": ["172.19.0.1/30"],
                "mtu": 1400,
                "auto_route": True,
                "strict_route": True,
                "sniff": True,
                "domain_strategy": "prefer_ipv4",
            }],
            "outbounds": _COMMON_OUTBOUNDS,
            "route": {
                "rules": _COMMON_RULES,
                "final": "proxy",
                "auto_detect_interface": True,
            },
            "experimental": {"cache_file": {"enabled": True}},
        },
    },
    {
        "name": "windows",
        "label": "Windows Service (WinTun + system proxy)",
        "is_default": False,
        "config": {
            "log": {"level": "error", "timestamp": True},
            "dns": _DNS_ADGUARD,
            "inbounds": [
                {
                    "type": "mixed",
                    "tag": "mixed-in",
                    "listen": "127.0.0.1",
                    "listen_port": 7890,
                    "sniff": True,
                },
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "address": ["172.19.0.1/30"],
                    "mtu": 1400,
                    "auto_route": True,
                    "strict_route": True,
                    "sniff": True,
                    "stack": "system",
                    "platform": {
                        "http_proxy": {
                            "enabled": True,
                            "server": "127.0.0.1",
                            "server_port": 7890,
                        }
                    },
                },
            ],
            "outbounds": _COMMON_OUTBOUNDS,
            "route": {
                "rules": _COMMON_RULES,
                "final": "proxy",
                "auto_detect_interface": True,
            },
            "experimental": {"cache_file": {"enabled": True}},
        },
    },
    {
        "name": "tproxy",
        "label": "TProxy — Router (OpenWRT / Linux)",
        "is_default": False,
        "config": {
            "log": {"level": "error", "timestamp": True},
            "dns": _DNS_ADGUARD,
            "inbounds": [
                {
                    "type": "tproxy",
                    "tag": "tproxy-in",
                    "listen": "0.0.0.0",
                    "listen_port": 7893,
                    "network": "tcp udp",
                    "sniff": True,
                },
                {
                    "type": "redirect",
                    "tag": "redirect-in",
                    "listen": "0.0.0.0",
                    "listen_port": 7892,
                    "sniff": True,
                },
                {
                    "type": "dns",
                    "tag": "dns-in",
                    "listen": "0.0.0.0",
                    "listen_port": 5353,
                },
            ],
            "outbounds": _COMMON_OUTBOUNDS + [{"tag": "dns-out", "type": "dns"}],
            "route": {
                "rules": [
                    {"inbound": "dns-in", "outbound": "dns-out"},
                    {"ip_is_private": True, "outbound": "direct"},
                ],
                "final": "proxy",
                "auto_detect_interface": True,
            },
            "experimental": {"cache_file": {"enabled": True}},
        },
    },
    {
        "name": "socks",
        "label": "SOCKS5 + HTTP — Manual proxy",
        "is_default": False,
        "config": {
            "log": {"level": "error", "timestamp": True},
            "inbounds": [
                {
                    "type": "socks",
                    "tag": "socks-in",
                    "listen": "127.0.0.1",
                    "listen_port": 7891,
                    "sniff": True,
                },
                {
                    "type": "http",
                    "tag": "http-in",
                    "listen": "127.0.0.1",
                    "listen_port": 7890,
                    "sniff": True,
                },
            ],
            "outbounds": _COMMON_OUTBOUNDS,
            "route": {
                "rules": [{"ip_is_private": True, "outbound": "direct"}],
                "final": "proxy",
            },
        },
    },
]


def get_builtin_config_json(name: str) -> str:
    for t in BUILTIN_TEMPLATES:
        if t["name"] == name:
            return json.dumps(t["config"], ensure_ascii=False)
    raise KeyError(f"Unknown built-in template: {name}")
