"""
Nginx configuration manager.

Default behaviour (no override uploaded):
  GET / → try_files /index.html @auth → 401 Basic Auth popup (browser native dialog)
  .htpasswd contains random credentials → login is always impossible (camouflage)

When user uploads a site:
  GET / → try_files /index.html @auth → serves override/index.html
  /override/* → static assets the page may reference
"""
import asyncio
import hashlib
import os
import secrets
import shutil
import zipfile
import io
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from api.config import settings
from api.routers.settings_router import get_runtime

BASE_DIR           = Path(__file__).parent.parent.parent
NGINX_DIR          = BASE_DIR / "nginx"
CONF_D_DIR         = NGINX_DIR / "conf.d"
OVERRIDE_DIR       = NGINX_DIR / "override"      # mounted as /var/www/override in nginx
HTPASSWD_DIR       = NGINX_DIR / "htpasswd"
HTPASSWD_FILE      = HTPASSWD_DIR / ".htpasswd"
TEMPLATES_DIR      = NGINX_DIR / "templates"
LOGS_DIR           = NGINX_DIR / "logs"
SITE_ENABLED_MARKER = NGINX_DIR / ".site_enabled"   # presence = site ON, absence = site OFF

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
    domain = domain or get_runtime("domain")
    h = _secret_hash()
    base = f"https://{domain}"
    return {
        "web_ui":         f"{base}/web/",
        "subscriptions":  f"{base}/{h[12:24]}/sub/",
        "adguard":        f"{base}/{h[24:36]}/adg/",
        "api":            f"{base}/{h[36:48]}/api/",
        "doh":            f"{base}/{h[48:60]}/doh/",   # AdGuard DoH proxy, per-user: .../doh/{sub_id}
        "api_docs":       f"{base}/api/docs",
    }


def get_doh_url(sub_id: str, domain: str = None) -> str:
    """Return the per-client AdGuard DoH URL for a given subscription ID."""
    paths = get_hidden_paths(domain)
    return paths["doh"].rstrip("/") + f"/{sub_id}"


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
    """
    Generate .htpasswd with random credentials.
    Uses openssl passwd (available on all Linux servers).
    The crypt module was removed in Python 3.13, so we avoid it entirely.
    """
    import subprocess as sp
    user = "user"
    password = secrets.token_hex(32)  # random, never shared with anyone
    try:
        result = sp.run(
            ["openssl", "passwd", "-6", password],
            capture_output=True, text=True, timeout=10,
        )
        hashed = result.stdout.strip()
        if not hashed:
            raise RuntimeError("openssl passwd returned empty output")
    except Exception:
        # Last resort: apr1 MD5 (widely supported, not as strong but fine for camouflage)
        import base64
        hashed = "$apr1$" + base64.b64encode(os.urandom(6)).decode()[:8] + "$" + secrets.token_hex(11)
    HTPASSWD_FILE.write_text(f"{user}:{hashed}\n", encoding="utf-8")
    HTPASSWD_FILE.chmod(0o640)


# ─── Nginx config generation ──────────────────────────────────────────────────

def generate_config(
    domain: str = None,
    adguard_enabled: bool = True,
    site_enabled: bool = None,
) -> str:
    from api.services.ip_ban import get_banned_ips
    if not domain:
        domain = get_runtime("domain")
    h = _secret_hash()
    ssl_cert, ssl_key = get_ssl_paths(domain)
    if site_enabled is None:
        site_enabled = get_site_enabled()

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("main.conf.j2")
    return template.render(
        domain=domain,
        secret_hash=h,
        ssl_cert=ssl_cert,
        ssl_key=ssl_key,
        adguard_enabled=adguard_enabled,
        site_enabled=site_enabled,
        banned_ips=get_banned_ips(),
        doh_path=f"/{h[48:60]}/doh",   # AdGuard DoH proxy path
    )


def write_config(config_text: str, filename: str = "singbox.conf") -> Path:
    path = CONF_D_DIR / filename
    path.write_text(config_text, encoding="utf-8")
    return path


# ─── Site on/off toggle ───────────────────────────────────────────────────────

def get_site_enabled() -> bool:
    """
    Returns whether the public site is enabled.
    Enabled  → root '/' tries /override/index.html first, falls back to 401 stub.
    Disabled → root '/' always shows 401 Basic Auth popup (default/safe state).
    """
    return SITE_ENABLED_MARKER.exists()


def set_site_enabled(enabled: bool) -> None:
    if enabled:
        SITE_ENABLED_MARKER.touch()
    else:
        SITE_ENABLED_MARKER.unlink(missing_ok=True)


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
    for item in OVERRIDE_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


# ─── Async subprocess helper ──────────────────────────────────────────────────

async def _run(*cmd: str, timeout: int = 30) -> tuple[bool, str]:
    """Run a command async without blocking the event loop."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0, stdout.decode(errors="replace")
    except asyncio.TimeoutError:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


# ─── Nginx process management ─────────────────────────────────────────────────

async def reload_nginx() -> tuple[bool, str]:
    ok, out = await _run("docker", "exec", "singbox_nginx", "nginx", "-s", "reload")
    if ok:
        return True, "OK"
    # Fallback: direct nginx call (if running without docker, e.g. in CI)
    ok2, out2 = await _run("nginx", "-s", "reload", timeout=10)
    return ok2, out2 or out


async def test_nginx_config() -> tuple[bool, str]:
    return await _run("docker", "exec", "singbox_nginx", "nginx", "-t")


async def get_access_logs(lines: int = 50) -> str:
    log_path = LOGS_DIR / "access.log"
    if not log_path.exists():
        return "Log file not found."
    try:
        # Use async file read to not block the event loop
        import aiofiles
        async with aiofiles.open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = await f.read()
        all_lines = content.splitlines()
        return "\n".join(all_lines[-lines:])
    except Exception as e:
        return str(e)


async def issue_ssl_cert(domain: str, email: str) -> tuple[bool, str]:
    """Issue Let's Encrypt certificate. Runs certbot non-blocking."""
    return await _run(
        "certbot", "certonly", "--nginx",
        "-d", domain,
        "--email", email,
        "--agree-tos", "--non-interactive", "--quiet",
        timeout=180,
    )
