"""
Built-in client subscription templates.

Architecture mirrors vpnbot's sing.json:
  - TUN inbound (stack: mixed) for Android/iOS/Linux/macOS/Windows
  - mixed inbound on 127.0.0.1:2080 for HTTP/SOCKS5 proxy mode
  - AdGuard DoH DNS via __dns_url__ placeholder (per-user URL injected at subscription time)
  - dns_bootstrap (TCP 8.8.8.8) resolves the DoH server hostname (avoids circular dependency)
  - Route order: sniff → hijack-dns → resolve (mixed inbound) → private IPs direct → user rules → final: proxy

Placeholders:
  {"tag": "proxy", "type": "__proxy__"}  — replaced with real outbound (VLESS/SS/Trojan/etc.)
  "__dns_url__"                           — replaced with https://{domain}/{doh_path}/{sub_id}
                                            enabling per-user AdGuard DNS stats and filtering

BUILTIN_TEMPLATES: seeded once on first start (only if the table is empty).
PRESET_TEMPLATES:  additional presets users can add manually via Web UI (not auto-seeded).
"""
import json

# ─── Single default template (mirrors vpnbot's sing.json) ────────────────────

_DEFAULT_CONFIG = {
    "log": {
        "level": "error",
        "timestamp": True,
    },
    "dns": {
        "servers": [
            {
                # AdGuard Home DoH — per-user URL injected at subscription build time.
                # DNS queries are visible in AdGuard per-client statistics.
                "tag": "dns_proxy",
                "address": "__dns_url__",
                "address_resolver": "dns_bootstrap",
                "strategy": "prefer_ipv4",
                "detour": "direct",
            },
            {
                # Bootstrap resolver: plain TCP to resolve the DoH server hostname.
                # Prevents the chicken-and-egg problem (need DNS to resolve DNS server).
                "tag": "dns_bootstrap",
                "address": "tcp://8.8.8.8",
                "detour": "direct",
            },
        ],
        "rules": [
            # All outbound DNS resolution goes through AdGuard (DoH, filtered, logged per-client)
            {"outbound": "any", "server": "dns_proxy", "disable_cache": False},
        ],
        "strategy": "ipv4_only",
        "final": "dns_proxy",
        "independent_cache": True,
    },
    "inbounds": [
        {
            # TUN — captures all device traffic (Android, iOS, macOS, Linux, Windows)
            "type": "tun",
            "tag": "tun-in",
            "address": ["172.19.0.1/30"],
            "mtu": 1400,
            "auto_route": True,
            "strict_route": True,
            "stack": "mixed",           # gVisor + System fallback (best compat)
            "domain_strategy": "prefer_ipv4",
            "sniff": True,
            "platform": {
                # Expose HTTP proxy on 127.0.0.1:2080 for apps that support system proxy
                "http_proxy": {
                    "enabled": True,
                    "server": "127.0.0.1",
                    "server_port": 2080,
                }
            },
        },
        {
            # Mixed inbound — HTTP/SOCKS5 on 127.0.0.1:2080 for manual proxy mode
            "type": "mixed",
            "tag": "in",
            "listen": "127.0.0.1",
            "listen_port": 2080,
            "sniff": True,
        },
    ],
    "outbounds": [
        # __proxy__ is replaced with the real outbound at subscription build time
        {"tag": "proxy", "type": "__proxy__"},
        {"tag": "direct", "type": "direct"},
        {"tag": "block",  "type": "block"},
    ],
    "route": {
        "rules": [
            # 1. Identify protocol/domain before routing decisions
            {"action": "sniff"},
            # 2. Capture DNS queries and route through our DNS stack
            {"protocol": "dns", "action": "hijack-dns"},
            # 3. Resolve domain names for traffic from the mixed proxy inbound
            {"inbound": "in", "action": "resolve", "strategy": "prefer_ipv4"},
            # 4. LAN / private IPs always go direct (never through VPN)
            {"ip_is_private": True, "outbound": "direct"},
            # NOTE: Additional user-defined routing rules are inserted here by the
            # server-side routing system (bot/web UI → singbox config.json route.rules).
        ],
        "final": "direct",              # Unmatched traffic goes direct (split-tunnel like vpnbot)
        "auto_detect_interface": True,
        "override_android_vpn": True,   # Needed on Android for TUN mode
    },
    "experimental": {
        "cache_file": {"enabled": True},
    },
}

# The one template seeded on first start
BUILTIN_TEMPLATES = [
    {
        "name": "default",
        "label": "Default — TUN + HTTP/SOCKS5 (Android, iOS, Linux, macOS, Windows)",
        "is_default": True,
        "config": _DEFAULT_CONFIG,
    },
]


# ─── Optional presets (not auto-seeded; users can add via Web UI) ─────────────
# These are provided as reference configs for common use-cases.
# Each must contain {"tag": "proxy", "type": "__proxy__"} placeholder.

PRESET_TEMPLATES = [
    {
        "name": "tun_fakeip",
        "label": "TUN + FakeIP (faster DNS resolution, split routing)",
        "config": {
            "log": {"level": "error", "timestamp": True},
            "dns": {
                "servers": [
                    {
                        "tag": "dns_proxy",
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
                        # FakeIP: instantly returns fake IPs for proxied traffic
                        "tag": "dns_fakeip",
                        "address": "fakeip",
                        "inet4_range": "198.18.0.0/15",
                        "inet6_range": "fc00::/18",
                    },
                ],
                "rules": [
                    {"outbound": "any", "server": "dns_proxy", "disable_cache": False},
                    {"query_type": ["A", "AAAA"], "server": "dns_fakeip"},
                ],
                "strategy": "ipv4_only",
                "final": "dns_proxy",
                "independent_cache": True,
            },
            "inbounds": [
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "address": ["172.19.0.1/30"],
                    "mtu": 1400,
                    "auto_route": True,
                    "strict_route": True,
                    "stack": "mixed",
                    "domain_strategy": "prefer_ipv4",
                    "sniff": True,
                    "platform": {"http_proxy": {"enabled": True, "server": "127.0.0.1", "server_port": 2080}},
                },
                {"type": "mixed", "tag": "in", "listen": "127.0.0.1", "listen_port": 2080, "sniff": True},
            ],
            "outbounds": [
                {"tag": "proxy", "type": "__proxy__"},
                {"tag": "direct", "type": "direct"},
                {"tag": "block",  "type": "block"},
            ],
            "route": {
                "rules": [
                    {"action": "sniff"},
                    {"protocol": "dns", "action": "hijack-dns"},
                    {"inbound": "in", "action": "resolve", "strategy": "prefer_ipv4"},
                    {"ip_is_private": True, "outbound": "direct"},
                ],
                "final": "direct",
                "auto_detect_interface": True,
                "override_android_vpn": True,
            },
            "experimental": {"cache_file": {"enabled": True}},
        },
    },
    {
        "name": "tproxy",
        "label": "TProxy — Router (OpenWRT / Linux gateway)",
        "config": {
            "log": {"level": "error", "timestamp": True},
            "dns": {
                "servers": [
                    {"tag": "dns_proxy", "address": "__dns_url__", "address_resolver": "dns_bootstrap", "strategy": "prefer_ipv4", "detour": "direct"},
                    {"tag": "dns_bootstrap", "address": "tcp://8.8.8.8", "detour": "direct"},
                ],
                "rules": [{"outbound": "any", "server": "dns_proxy"}],
                "strategy": "ipv4_only",
                "final": "dns_proxy",
                "independent_cache": True,
            },
            "inbounds": [
                {"type": "tproxy", "tag": "tproxy-in", "listen": "0.0.0.0", "listen_port": 7893, "network": "tcp udp", "sniff": True},
                {"type": "redirect", "tag": "redirect-in", "listen": "0.0.0.0", "listen_port": 7892, "sniff": True},
                {"type": "dns", "tag": "dns-in", "listen": "0.0.0.0", "listen_port": 5353},
            ],
            "outbounds": [
                {"tag": "proxy", "type": "__proxy__"},
                {"tag": "direct", "type": "direct"},
                {"tag": "block",  "type": "block"},
                {"tag": "dns-out", "type": "dns"},
            ],
            "route": {
                "rules": [
                    {"inbound": "dns-in", "outbound": "dns-out"},
                    {"ip_is_private": True, "outbound": "direct"},
                ],
                "final": "direct",
                "auto_detect_interface": True,
            },
            "experimental": {"cache_file": {"enabled": True}},
        },
    },
    {
        "name": "socks",
        "label": "SOCKS5 + HTTP only (manual proxy, no TUN)",
        "config": {
            "log": {"level": "error", "timestamp": True},
            "inbounds": [
                {"type": "socks", "tag": "socks-in", "listen": "127.0.0.1", "listen_port": 7891, "sniff": True},
                {"type": "http",  "tag": "http-in",  "listen": "127.0.0.1", "listen_port": 2080, "sniff": True},
            ],
            "outbounds": [
                {"tag": "proxy", "type": "__proxy__"},
                {"tag": "direct", "type": "direct"},
                {"tag": "block",  "type": "block"},
            ],
            "route": {
                "rules": [{"ip_is_private": True, "outbound": "direct"}],
                "final": "direct",
            },
        },
    },
]


def get_builtin_config_json(name: str) -> str:
    for t in BUILTIN_TEMPLATES:
        if t["name"] == name:
            return json.dumps(t["config"], ensure_ascii=False)
    raise KeyError(f"Unknown built-in template: {name}")


def get_preset_config_json(name: str) -> str:
    for t in PRESET_TEMPLATES:
        if t["name"] == name:
            return json.dumps(t["config"], ensure_ascii=False)
    raise KeyError(f"Unknown preset template: {name}")
