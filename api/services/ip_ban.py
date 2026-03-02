"""
IP ban management.

Ban list is stored in nginx/.banned_ips.json:
  { "1.2.3.4": {"reason": "manual", "auto": false, "added_at": 1735000000} }

A whitelist of always-trusted IPs (Telegram subnets) is hard-coded so
they can never be banned by auto-analysis.

After every change the nginx config is regenerated and Nginx is reloaded.
"""
import json
import re
import time
from pathlib import Path
from typing import Optional

# Same BASE_DIR as nginx_service
BASE_DIR      = Path(__file__).parent.parent.parent
NGINX_DIR     = BASE_DIR / "nginx"
BANNED_FILE   = NGINX_DIR / ".banned_ips.json"
LOGS_DIR      = NGINX_DIR / "logs"

# Telegram IP ranges (never auto-ban these)
_TELEGRAM_NETS = [
    "149.154.160.0/20",
    "91.108.4.0/22",
    "91.108.8.0/22",
    "91.108.12.0/22",
    "91.108.16.0/22",
    "91.108.56.0/22",
    "95.161.64.0/20",
    "185.76.151.0/24",
]

# Suspicious patterns in Nginx access logs (GETs to probe paths, etc.)
_SCAN_PATTERNS = [
    r"(\.php|\.asp|\.env|\.git|\.svn|\.bak|xmlrpc|wp-login|wp-admin|"
    r"phpmyadmin|cgi-bin|shell|eval|passwd|etc/shadow|/proc/self)",
    r"(CONNECT|PROPFIND|TRACE|OPTIONS)\s",
]
_SCAN_RE = re.compile("|".join(_SCAN_PATTERNS), re.IGNORECASE)


# ─── Persistence ──────────────────────────────────────────────────────────────

def _load() -> dict:
    if BANNED_FILE.exists():
        try:
            return json.loads(BANNED_FILE.read_text())
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    BANNED_FILE.write_text(json.dumps(data, indent=2))


# ─── Public API ───────────────────────────────────────────────────────────────

def get_banned_list() -> list[dict]:
    data = _load()
    return [
        {"ip": ip, **meta}
        for ip, meta in sorted(data.items(), key=lambda x: x[1].get("added_at", 0), reverse=True)
    ]


def add_ip(ip: str, reason: str = "manual", auto: bool = False) -> None:
    data = _load()
    data[ip] = {"reason": reason, "auto": auto, "added_at": int(time.time())}
    _save(data)


def remove_ip(ip: str) -> bool:
    data = _load()
    if ip not in data:
        return False
    del data[ip]
    _save(data)
    return True


def get_banned_ips() -> list[str]:
    """Return plain list of banned IP strings (for nginx template)."""
    return list(_load().keys())


def clear_auto_banned() -> int:
    """Remove all auto-added entries; returns count removed."""
    data = _load()
    before = len(data)
    data = {ip: m for ip, m in data.items() if not m.get("auto")}
    _save(data)
    return before - len(data)


# ─── Log analysis ─────────────────────────────────────────────────────────────

def analyze_logs(threshold: int = 30) -> list[dict]:
    """
    Scan nginx access.log for suspicious IPs.
    Returns list of dicts: {ip, requests, scan_hits, reason}.
    IPs already in ban list are excluded from results.
    """
    log_path = LOGS_DIR / "access.log"
    if not log_path.exists():
        return []

    already_banned = set(_load().keys())
    ip_counts: dict[str, int] = {}
    ip_scans:  dict[str, int] = {}

    try:
        for line in log_path.read_text(errors="replace").splitlines()[-50_000:]:
            # Standard nginx log: starts with IP address
            parts = line.split()
            if not parts:
                continue
            ip = parts[0]
            if not _looks_like_ip(ip):
                continue
            ip_counts[ip] = ip_counts.get(ip, 0) + 1
            if _SCAN_RE.search(line):
                ip_scans[ip] = ip_scans.get(ip, 0) + 1
    except Exception:
        return []

    suspicious = []
    for ip, count in ip_counts.items():
        if ip in already_banned:
            continue
        if _is_whitelisted(ip):
            continue
        scans = ip_scans.get(ip, 0)
        if count >= threshold or scans >= 5:
            reason = []
            if count >= threshold:
                reason.append(f"{count} requests")
            if scans >= 5:
                reason.append(f"{scans} scan probes")
            suspicious.append({
                "ip": ip,
                "requests": count,
                "scan_hits": scans,
                "reason": ", ".join(reason),
            })

    return sorted(suspicious, key=lambda x: x["scan_hits"] * 10 + x["requests"], reverse=True)[:50]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _looks_like_ip(s: str) -> bool:
    return bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", s))


def _is_whitelisted(ip: str) -> bool:
    """Very simple prefix-based whitelist check (good enough for /8-/24 ranges)."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        for net in _TELEGRAM_NETS:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
    except ValueError:
        pass
    return False


# ─── Nginx sync ───────────────────────────────────────────────────────────────

async def sync_to_nginx() -> tuple[bool, str]:
    """Regenerate nginx config with current deny list and reload Nginx."""
    from api.services import nginx_service
    from api.routers.settings_router import get_runtime
    config_text = nginx_service.generate_config(domain=get_runtime("domain"))
    nginx_service.write_config(config_text)
    ok, msg = await nginx_service.test_nginx_config()
    if not ok:
        return False, f"Config test failed: {msg}"
    return await nginx_service.reload_nginx()
