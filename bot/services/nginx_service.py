"""
Nginx configuration manager.

Default behaviour (no override uploaded):
  GET / → try_files /index.html @auth → 401 Basic Auth popup (browser native dialog)
  .htpasswd contains random credentials → login is always impossible (camouflage)

When user uploads a site:
  GET / → try_files /index.html @auth → serves override/index.html
  /override/* → static assets the page may reference
"""
import hashlib
import os
import secrets
import subprocess
import zipfile
import io
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from bot.config import settings

BASE_DIR      = Path(__file__).parent.parent.parent
NGINX_DIR     = BASE_DIR / "nginx"
CONF_D_DIR    = NGINX_DIR / "conf.d"
OVERRIDE_DIR  = NGINX_DIR / "override"      # mounted as /var/www/override in nginx
HTPASSWD_DIR  = NGINX_DIR / "htpasswd"
HTPASSWD_FILE = HTPASSWD_DIR / ".htpasswd"
TEMPLATES_DIR = NGINX_DIR / "templates"
LOGS_DIR      = NGINX_DIR / "logs"

# Ensure dirs exist on import
for _d in (CONF_D_DIR, OVERRIDE_DIR, HTPASSWD_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _secret_hash() -> str:
    return hashlib.sha256(settings.secret_key.encode()).hexdigest()


def get_ssl_paths(domain: str):
    letsencrypt = Path(f"/etc/letsencrypt/live/{domain}")
    if letsencrypt.exists():
        return str(letsencrypt / "fullchain.pem"), str(letsencrypt / "privkey.pem")
    return str(BASE_DIR / "data/certs/fullchain.pem"), str(BASE_DIR / "data/certs/privkey.pem")


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


# ─── .htpasswd generation ─────────────────────────────────────────────────────

def ensure_htpasswd() -> None:
    """
    Create .htpasswd with random credentials so the 401 Basic Auth popup
    is always displayed but login is impossible (camouflage effect).
    """
    if HTPASSWD_FILE.exists():
        return
    _regen_htpasswd()


def _regen_htpasswd() -> None:
    import crypt  # Unix only; falls back to openssl on Linux servers
    user = "user"
    password = secrets.token_hex(32)  # random, never shared
    try:
        hashed = crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))
    except Exception:
        # Fallback: use openssl passwd
        result = subprocess.run(
            ["openssl", "passwd", "-6", password],
            capture_output=True, text=True
        )
        hashed = result.stdout.strip()
    HTPASSWD_FILE.write_text(f"{user}:{hashed}\n", encoding="utf-8")
    HTPASSWD_FILE.chmod(0o640)


# ─── Nginx config generation ──────────────────────────────────────────────────

def generate_config(
    domain: str = None,
    adguard_enabled: bool = True,
) -> str:
    domain = domain or settings.domain
    h = _secret_hash()
    ssl_cert, ssl_key = get_ssl_paths(domain)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("main.conf.j2")
    return template.render(
        domain=domain,
        secret_hash=h,
        ssl_cert=ssl_cert,
        ssl_key=ssl_key,
        adguard_enabled=adguard_enabled,
    )


def write_config(config_text: str, filename: str = "singbox.conf") -> Path:
    path = CONF_D_DIR / filename
    path.write_text(config_text, encoding="utf-8")
    return path


# ─── Override site management ─────────────────────────────────────────────────

def override_status() -> dict:
    """Return info about the current override site."""
    index = OVERRIDE_DIR / "index.html"
    if not index.exists():
        return {"active": False, "files": []}
    files = [f.name for f in OVERRIDE_DIR.iterdir() if f.is_file()]
    size = sum(f.stat().st_size for f in OVERRIDE_DIR.rglob("*") if f.is_file())
    return {"active": True, "files": files, "size_kb": round(size / 1024, 1)}


def save_override_html(content: bytes) -> None:
    """Save a single HTML file as the override index."""
    _clear_override()
    (OVERRIDE_DIR / "index.html").write_bytes(content)


def save_override_zip(content: bytes) -> int:
    """
    Extract a ZIP archive into the override directory.
    Looks for index.html at the top level or one level deep.
    Returns number of extracted files.
    """
    _clear_override()
    count = 0
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        members = zf.namelist()
        # Detect single-folder wrapper (e.g. site/index.html → strip prefix)
        prefix = ""
        top_dirs = {m.split("/")[0] for m in members if "/" in m}
        if (
            len(top_dirs) == 1
            and all(m.startswith(list(top_dirs)[0] + "/") for m in members if not m.endswith("/"))
        ):
            prefix = list(top_dirs)[0] + "/"

        for member in members:
            if member.endswith("/"):
                continue  # skip directory entries
            rel = member[len(prefix):] if prefix and member.startswith(prefix) else member
            if not rel:
                continue
            dest = OVERRIDE_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))
            count += 1

    # If no index.html at root, try to find one level deep
    if not (OVERRIDE_DIR / "index.html").exists():
        for f in OVERRIDE_DIR.rglob("index.html"):
            f.rename(OVERRIDE_DIR / "index.html")
            break

    return count


def remove_override() -> None:
    """Remove the override site — reverts to 401 auth popup."""
    _clear_override()


def _clear_override() -> None:
    import shutil
    for item in OVERRIDE_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


# ─── Nginx process management ─────────────────────────────────────────────────

async def reload_nginx() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["docker", "exec", "singbox_nginx", "nginx", "-s", "reload"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, "OK"
        # Fallback: direct call
        result2 = subprocess.run(
            ["nginx", "-s", "reload"],
            capture_output=True, text=True, timeout=10,
        )
        return result2.returncode == 0, result2.stderr or result2.stdout
    except Exception as e:
        return False, str(e)


async def test_nginx_config() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["docker", "exec", "singbox_nginx", "nginx", "-t"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0, result.stderr or result.stdout
    except Exception as e:
        return False, str(e)


async def get_access_logs(lines: int = 50) -> str:
    log_path = LOGS_DIR / "access.log"
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
