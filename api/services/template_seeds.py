"""
Built-in client subscription templates.

Each template is a full sing-box client config JSON where the proxy
outbound is marked with {"tag": "proxy", "type": "__proxy__"}.
At subscription time this placeholder is replaced with the real outbound
built from the client credentials + inbound settings.

Add to outbounds only what is needed by the template.
The __proxy__ placeholder MUST be present exactly once.
"""
import json

# ─── Common route rules shared by most templates ───────────────────────────
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

_DNS_BASE = {
    "servers": [
        {"tag": "dns_proxy",  "type": "tls", "server": "8.8.8.8"},
        {"tag": "dns_direct", "type": "udp", "server": "223.5.5.5", "detour": "direct"},
    ],
    "rules": [{"outbound": "any", "server": "dns_direct"}],
    "strategy": "ipv4_only",
    "final": "dns_proxy",
    "independent_cache": True,
}

# ─── Template definitions ──────────────────────────────────────────────────

BUILTIN_TEMPLATES = [
    {
        "name": "tun",
        "label": "TUN — Phone / PC (Android, iOS, Linux, macOS)",
        "is_default": True,
        "config": {
            "log": {"level": "info"},
            "dns": _DNS_BASE,
            "inbounds": [{
                "type": "tun",
                "tag": "tun-in",
                "address": ["172.19.0.1/30"],
                "auto_route": True,
                "strict_route": True,
                "sniff": True,
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
        "label": "TUN + FakeIP — Phone / PC (advanced DNS)",
        "is_default": False,
        "config": {
            "log": {"level": "info"},
            "dns": {
                "servers": [
                    {"tag": "dns_proxy",  "type": "tls", "server": "8.8.8.8"},
                    {"tag": "dns_direct", "type": "udp", "server": "223.5.5.5", "detour": "direct"},
                    {"tag": "dns_fakeip", "type": "fakeip",
                     "inet4_range": "198.18.0.0/15", "inet6_range": "fc00::/18"},
                ],
                "rules": [
                    {"query_type": ["A", "AAAA"], "server": "dns_fakeip"},
                    {"outbound": "any", "server": "dns_direct"},
                ],
                "strategy": "ipv4_only",
                "final": "dns_proxy",
                "independent_cache": True,
            },
            "inbounds": [{
                "type": "tun",
                "tag": "tun-in",
                "address": ["172.19.0.1/30"],
                "auto_route": True,
                "strict_route": True,
                "sniff": True,
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
            "log": {"level": "info"},
            "dns": _DNS_BASE,
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
            "log": {"level": "info"},
            "dns": {
                **_DNS_BASE,
                "final": "dns_proxy",
            },
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
            "log": {"level": "info"},
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
