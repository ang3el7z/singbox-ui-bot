"""
Nginx configuration manager.
Generates nginx.conf from Jinja2 template and writes it to nginx/conf.d/.

Stub modes:
  auth   — Basic Auth challenge (browser shows native login dialog, always 401).
            Looks like a legitimate access-controlled server. Default.
  custom — User-uploaded HTML page served as static content.
  none   — Return 404 for root.
"""
import base64
import hashlib
import os
import subprocess
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from bot.config import settings

BASE_DIR = Path(__file__).parent.parent.parent
NGINX_DIR = BASE_DIR / "nginx"
CONF_D_DIR = NGINX_DIR / "conf.d"
STUBS_DIR = NGINX_DIR / "stubs"
TEMPLATES_DIR = NGINX_DIR / "templates"

CONF_D_DIR.mkdir(parents=True, exist_ok=True)

STUB_MODES = {
    "auth":   "🔒 Окно авторизации (по умолчанию)",
    "custom": "📁 Свой HTML",
    "none":   "❌ Возвращать 404",
}


def _secret_hash() -> str:
    return hashlib.sha256(settings.secret_key.encode()).hexdigest()


def _make_htpasswd_sha1(username: str, password: str) -> str:
    """Generate a {SHA} htpasswd line (nginx-compatible, no external deps)."""
    digest = hashlib.sha1(password.encode()).digest()
    b64 = base64.b64encode(digest).decode()
    return f"{username}:{{SHA}}{b64}"


def get_ssl_paths(domain: str) -> tuple[str, str]:
    letsencrypt = Path(f"/etc/letsencrypt/live/{domain}")
    if letsencrypt.exists():
        return str(letsencrypt / "fullchain.pem"), str(letsencrypt / "privkey.pem")
    return str(BASE_DIR / "data/certs/fullchain.pem"), str(BASE_DIR / "data/certs/privkey.pem")


def ensure_htpasswd() -> Path:
    """
    Create .htpasswd in nginx/conf.d/ if it doesn't exist.
    Uses a random password derived from SECRET_KEY so it's stable across restarts
    but never exposed to anyone.
    """
    htpasswd_path = CONF_D_DIR / ".htpasswd"
    if not htpasswd_path.exists():
        # Deterministic but secret password from SECRET_KEY
        password = hashlib.sha256(f"htpasswd:{settings.secret_key}".encode()).hexdigest()
        htpasswd_path.write_text(
            _make_htpasswd_sha1("admin", password) + "\n",
            encoding="utf-8",
        )
    return htpasswd_path


def generate_config(
    domain: str = None,
    stub_mode: str = None,
    adguard_enabled: bool = True,
    auth_realm: str = "Protected Area",
) -> str:
    domain = domain or settings.domain
    stub_mode = stub_mode or getattr(settings, "stub_mode", "auth")
    secret_hash = _secret_hash()
    ssl_cert, ssl_key = get_ssl_paths(domain)

    if stub_mode == "auth":
        ensure_htpasswd()

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("main.conf.j2")
    return template.render(
        domain=domain,
        secret_hash=secret_hash,
        stub_mode=stub_mode,
        auth_realm=auth_realm,
        ssl_cert=ssl_cert,
        ssl_key=ssl_key,
        adguard_enabled=adguard_enabled,
    )


def write_config(config_text: str, filename: str = "singbox.conf") -> Path:
    path = CONF_D_DIR / filename
    path.write_text(config_text, encoding="utf-8")
    return path


def get_hidden_paths(domain: str = None) -> dict:
    domain = domain or settings.domain
    h = _secret_hash()
    base = f"https://{domain}"
    return {
        "panel":          f"{base}/{h[:12]}/panel/",
        "subscriptions":  f"{base}/{h[12:24]}/sub/",
        "adguard":        f"{base}/{h[24:36]}/adg/",
        "federation_api": f"{base}/{h[36:48]}/api/",
    }


def get_custom_stub_path() -> Path:
    return STUBS_DIR / "custom" / "index.html"


def has_custom_stub() -> bool:
    return get_custom_stub_path().exists()


def save_custom_stub(content: bytes) -> None:
    path = get_custom_stub_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def reload_nginx() -> tuple[bool, str]:
    for cmd in (
        ["docker", "exec", "singbox_nginx", "nginx", "-s", "reload"],
        ["nginx", "-s", "reload"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return True, "OK"
        except FileNotFoundError:
            continue
        except Exception as e:
            return False, str(e)
    return False, "nginx not found"


async def test_nginx_config() -> tuple[bool, str]:
    for cmd in (
        ["docker", "exec", "singbox_nginx", "nginx", "-t"],
        ["nginx", "-t"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.returncode == 0, r.stderr or r.stdout
        except FileNotFoundError:
            continue
        except Exception as e:
            return False, str(e)
    return False, "nginx not found"


async def get_access_logs(lines: int = 50) -> str:
    log_path = NGINX_DIR / "logs" / "access.log"
    if not log_path.exists():
        return "Файл логов не найден."
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except Exception as e:
        return str(e)


async def issue_ssl_cert(domain: str, email: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [
                "certbot", "certonly", "--nginx",
                "-d", domain,
                "--email", email,
                "--agree-tos", "--non-interactive", "--quiet",
            ],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)
