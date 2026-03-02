"""
Nginx configuration manager.
Uses Jinja2 templates to generate nginx.conf and writes it to the nginx/conf.d directory.
Stub sites are static HTML served by Nginx.
"""
import hashlib
import os
import asyncio
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

STUB_THEMES = {
    "default": "Минималистичный (тёмный)",
    "business": "Технические работы",
    "blog": "Личный блог",
    "custom": "Пользовательская",
}


def _secret_hash() -> str:
    return hashlib.sha256(settings.secret_key.encode()).hexdigest()


def get_ssl_paths(domain: str):
    letsencrypt = Path(f"/etc/letsencrypt/live/{domain}")
    if letsencrypt.exists():
        return str(letsencrypt / "fullchain.pem"), str(letsencrypt / "privkey.pem")
    # Fallback to local certs
    return str(BASE_DIR / "data/certs/fullchain.pem"), str(BASE_DIR / "data/certs/privkey.pem")


def generate_config(
    domain: str = None,
    stub_theme: str = None,
    adguard_enabled: bool = True,
) -> str:
    domain = domain or settings.domain
    stub_theme = stub_theme or settings.stub_theme
    secret_hash = _secret_hash()
    ssl_cert, ssl_key = get_ssl_paths(domain)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("main.conf.j2")
    return template.render(
        domain=domain,
        secret_hash=secret_hash,
        stub_theme=stub_theme,
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
    secret_hash = _secret_hash()
    base = f"https://{domain}"
    return {
        "panel": f"{base}/{secret_hash[:12]}/panel/",
        "subscriptions": f"{base}/{secret_hash[12:24]}/sub/",
        "adguard": f"{base}/{secret_hash[24:36]}/adg/",
        "federation_api": f"{base}/{secret_hash[36:48]}/api/",
    }


async def reload_nginx() -> tuple[bool, str]:
    """Reload Nginx inside the container. Works via docker exec or direct nginx -s reload."""
    try:
        # Try docker exec first
        result = subprocess.run(
            ["docker", "exec", "singbox_nginx", "nginx", "-s", "reload"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, "OK"
        # Fallback: direct call (if running inside nginx container)
        result2 = subprocess.run(
            ["nginx", "-s", "reload"],
            capture_output=True, text=True, timeout=10
        )
        return result2.returncode == 0, result2.stderr or result2.stdout
    except Exception as e:
        return False, str(e)


async def test_nginx_config() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["docker", "exec", "singbox_nginx", "nginx", "-t"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0, result.stderr or result.stdout
    except Exception as e:
        return False, str(e)


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
    """Run certbot to obtain Let's Encrypt certificate."""
    try:
        result = subprocess.run(
            [
                "certbot", "certonly", "--nginx",
                "-d", domain,
                "--email", email,
                "--agree-tos", "--non-interactive", "--quiet",
            ],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def list_stub_themes() -> dict:
    available = {}
    for name, label in STUB_THEMES.items():
        if (STUBS_DIR / name / "index.html").exists() or name == "custom":
            available[name] = label
    return available
