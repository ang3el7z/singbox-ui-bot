"""
Update/reinstall orchestration:
- reads git update metadata
- starts detached maintenance jobs in helper containers
- tracks job state/logs
"""
from __future__ import annotations

import http.client
import json
import re
import shlex
import socket
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from api.services.backup_service import create_backup_file, get_backup_storage_dir


PROJECT_DIR = Path("/opt/singbox-ui-bot")
if not PROJECT_DIR.exists():
    PROJECT_DIR = Path(__file__).parent.parent.parent

STATE_FILE = Path("/app/data/update_state.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
UPDATE_INFO_CACHE_FILE = Path("/app/data/update_info_cache.json")
UPDATE_INFO_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

RUNNER_IMAGE = "singbox-ui-bot-app:latest"
REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
DOCKER_SOCK = Path("/var/run/docker.sock")
INSTALL_VERSION_FILES = [
    Path("/app/host_data/install_version.json"),
    PROJECT_DIR / "data" / "install_version.json",
    Path("/app/data/install_version.json"),
]

BACKUP_ROOT = get_backup_storage_dir()
BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
BACKUP_HOME = str(BACKUP_ROOT)

ACTION_UPDATE = "update"
ACTION_REINSTALL = "reinstall"
REINSTALL_MODE_PRESERVE = "preserve"
REINSTALL_MODE_CLEAN = "clean"

TARGET_CURRENT = "current"
TARGET_LATEST_TAG = "latest_tag"
TARGET_CUSTOM = "custom"
TARGETS = {TARGET_CURRENT, TARGET_LATEST_TAG, TARGET_CUSTOM}

_UPDATE_CACHE_LOCK = threading.Lock()
_UPDATE_CACHE_DATA: dict[str, Any] = {}
_UPDATE_CACHE_TS = 0.0
_UPDATE_CACHE_MAX_AGE_SECONDS = 300


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as e:
        return 1, str(e)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection over Docker unix socket."""

    def __init__(self, socket_path: str, timeout: int = 30):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def _docker_name(name: str) -> str:
    return urllib.parse.quote(name, safe="")


def _docker_error_text(status: int, body: str) -> str:
    text = (body or "").strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            msg = (parsed.get("message") or "").strip()
            if msg:
                text = msg
        except Exception:
            pass
    return f"Docker API error {status}: {text or 'unknown error'}"


def _docker_request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> tuple[int, str]:
    if not DOCKER_SOCK.exists():
        raise RuntimeError(
            "Docker socket is not mounted inside app container. "
            "Expected /var/run/docker.sock."
        )

    payload: bytes | None = None
    headers: dict[str, str] = {}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    conn = _UnixSocketHTTPConnection(str(DOCKER_SOCK), timeout=timeout)
    try:
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, raw.decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"Docker API request failed: {e}") from e
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(data: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_update_info_cache_from_disk() -> tuple[dict[str, Any], float]:
    if not UPDATE_INFO_CACHE_FILE.exists():
        return {}, 0.0
    try:
        raw = json.loads(UPDATE_INFO_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}, 0.0
    if not isinstance(raw, dict):
        return {}, 0.0
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    ts = raw.get("cached_at")
    try:
        cached_at = float(ts)
    except (TypeError, ValueError):
        cached_at = 0.0
    return data, cached_at


def _save_update_info_cache_to_disk(data: dict[str, Any], cached_at: float) -> None:
    payload = {"cached_at": cached_at, "data": data}
    UPDATE_INFO_CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _set_update_info_cache(data: dict[str, Any], cached_at: float | None = None) -> None:
    global _UPDATE_CACHE_DATA, _UPDATE_CACHE_TS
    ts = time.time() if cached_at is None else float(cached_at)
    _UPDATE_CACHE_DATA = dict(data)
    _UPDATE_CACHE_TS = ts
    try:
        _save_update_info_cache_to_disk(_UPDATE_CACHE_DATA, ts)
    except Exception:
        pass


def _git_value(*args: str, default: str = "") -> str:
    code, out = _run(["git", *args], cwd=PROJECT_DIR)
    if code != 0:
        return default
    return out.strip() or default


def _load_install_version() -> dict[str, Any]:
    for candidate in INSTALL_VERSION_FILES:
        try:
            if not candidate.exists():
                continue
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            continue
    return {}


def _resolve_current_version(
    *,
    current_tag: str,
    current_branch: str,
    current_commit: str,
    current_commit_full: str,
) -> tuple[str, str]:
    """
    Resolve a human-readable current version with stable fallbacks:
      1) exact git tag
      2) git describe (--tags --always --dirty)
      3) install metadata (if commit matches current HEAD)
      4) branch@short-commit
      5) dev
    Returns (version, source).
    """
    if current_tag:
        return current_tag, "git_tag_exact"

    described = _git_value("describe", "--tags", "--always", "--dirty", "--abbrev=7", default="")
    if described:
        # If describe falls back to a plain hash, include branch for readability.
        if described == current_commit and current_branch and current_branch != "HEAD":
            return f"{current_branch}@{current_commit}", "git_branch_commit"
        return described, "git_describe"

    install_meta = _load_install_version()
    meta_commit = str(install_meta.get("commit") or "").strip()
    meta_version = str(install_meta.get("version") or "").strip()
    if meta_version and (not meta_commit or not current_commit_full or meta_commit == current_commit_full):
        return meta_version, "install_metadata"

    if current_branch and current_branch != "HEAD" and current_commit and current_commit != "-":
        return f"{current_branch}@{current_commit}", "git_branch_commit"

    if current_commit and current_commit != "-":
        return current_commit, "git_commit"

    return "dev", "fallback_dev"


def _git_tag_notes(tag: str) -> str:
    """
    Read release notes for an annotated tag.
    For lightweight tags this may be empty.
    """
    value = (tag or "").strip()
    if not value:
        return ""

    code, out = _run(
        ["git", "for-each-ref", f"refs/tags/{value}", "--format=%(contents)"],
        cwd=PROJECT_DIR,
    )
    if code != 0:
        return ""

    text = (out or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    # Keep payload small for UI/API.
    return text[:3500]


def _parse_tag_notes_i18n(text: str) -> dict[str, str]:
    """
    Parse localized release notes from a tag message.
    Supported section marker format (one per line):
      [lang:ru]
      [lang:en]
      [lang:de]
    If no markers are present, returns an empty dict and clients should use raw text.
    """
    src = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not src.strip():
        return {}

    marker_re = re.compile(r"^\[lang:([a-zA-Z0-9_-]{2,16})\]\s*$")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    found_markers = False

    for line in src.split("\n"):
        match = marker_re.match(line.strip())
        if match:
            found_markers = True
            current = match.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)

    if not found_markers:
        return {}

    out: dict[str, str] = {}
    for lang, lines in sections.items():
        chunk = "\n".join(lines).strip()
        if chunk:
            out[lang] = chunk[:3500]
    return out


def _list_remote_branches(limit: int = 30) -> list[str]:
    code, out = _run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
        cwd=PROJECT_DIR,
    )
    if code != 0:
        return []
    branches: list[str] = []
    for raw in out.splitlines():
        item = raw.strip()
        if not item or item == "origin/HEAD":
            continue
        if item.startswith("origin/"):
            item = item[len("origin/"):]
        branches.append(item)
    unique: list[str] = []
    seen = set()
    for b in branches:
        if b in seen:
            continue
        seen.add(b)
        unique.append(b)
    return unique[:limit]


def get_update_info(refresh_remote: bool = True) -> dict[str, Any]:
    if not (PROJECT_DIR / ".git").exists():
        install_meta = _load_install_version()
        meta_version = str(install_meta.get("version") or "").strip()
        meta_ref = str(install_meta.get("ref") or "").strip()
        meta_commit_full = str(install_meta.get("commit") or "").strip()
        meta_commit = meta_commit_full[:7] if meta_commit_full else "-"

        if meta_version:
            current_version = meta_version
            current_version_source = "install_metadata"
        elif meta_ref and meta_commit != "-":
            current_version = f"{meta_ref}@{meta_commit}"
            current_version_source = "install_metadata_ref"
        elif meta_commit != "-":
            current_version = meta_commit
            current_version_source = "install_metadata_commit"
        else:
            current_version = "dev"
            current_version_source = "fallback_dev"

        return {
            "project_dir": str(PROJECT_DIR),
            "current_branch": meta_ref or "-",
            "current_commit": meta_commit,
            "current_tag": "",
            "current_version": current_version,
            "current_version_source": current_version_source,
            "latest_tag": "",
            "latest_tag_notes": "",
            "latest_tag_notes_i18n": {},
            "remote_branch_commit": "",
            "update_available_branch": False,
            "update_available_tag": False,
            "remote_branches": [],
            "git_error": f"Git repository not found in {PROJECT_DIR}",
        }

    git_error = ""
    if refresh_remote:
        code, out = _run(["git", "fetch", "--tags", "--prune", "origin"], cwd=PROJECT_DIR, timeout=45)
        if code != 0:
            git_error = out or "git fetch failed"

    current_branch = _git_value("rev-parse", "--abbrev-ref", "HEAD", default="main")
    current_commit = _git_value("rev-parse", "--short", "HEAD", default="-")
    current_commit_full = _git_value("rev-parse", "HEAD", default="")
    current_tag = _git_value("describe", "--tags", "--exact-match", default="")
    current_version, current_version_source = _resolve_current_version(
        current_tag=current_tag,
        current_branch=current_branch,
        current_commit=current_commit,
        current_commit_full=current_commit_full,
    )

    tags_raw = _git_value("tag", "--sort=-v:refname", default="")
    latest_tag = tags_raw.splitlines()[0].strip() if tags_raw.strip() else ""
    latest_tag_notes = _git_tag_notes(latest_tag)
    latest_tag_notes_i18n = _parse_tag_notes_i18n(latest_tag_notes)

    remote_commit = _git_value("rev-parse", f"origin/{current_branch}", default="")
    remote_commit_short = remote_commit[:7] if remote_commit else ""
    update_available_branch = bool(
        current_commit_full and remote_commit and current_commit_full != remote_commit
    )
    update_available_tag = bool(latest_tag and latest_tag != current_tag)

    return {
        "project_dir": str(PROJECT_DIR),
        "current_branch": current_branch,
        "current_commit": current_commit,
        "current_tag": current_tag,
        "current_version": current_version,
        "current_version_source": current_version_source,
        "latest_tag": latest_tag,
        "latest_tag_notes": latest_tag_notes,
        "latest_tag_notes_i18n": latest_tag_notes_i18n,
        "remote_branch_commit": remote_commit_short,
        "update_available_branch": update_available_branch,
        "update_available_tag": update_available_tag,
        "remote_branches": _list_remote_branches(),
        "git_error": git_error,
    }


def refresh_update_info_cache(refresh_remote: bool = True) -> dict[str, Any]:
    """
    Force refresh update info and store it in the shared cache.
    Used by background scheduler.
    """
    fresh = get_update_info(refresh_remote=refresh_remote)
    with _UPDATE_CACHE_LOCK:
        _set_update_info_cache(fresh)
    return fresh


def get_update_info_cached(
    refresh_remote: bool = False,
    max_age_seconds: int = _UPDATE_CACHE_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """
    Return cached update info if fresh enough, otherwise rebuild and cache it.
    `refresh_remote=False` keeps this endpoint fast; background scheduler updates
    the cache with remote fetches periodically.
    """
    now = time.time()
    max_age = max(0, int(max_age_seconds))

    with _UPDATE_CACHE_LOCK:
        global _UPDATE_CACHE_DATA, _UPDATE_CACHE_TS
        if not _UPDATE_CACHE_DATA:
            disk_data, disk_ts = _load_update_info_cache_from_disk()
            if disk_data:
                _UPDATE_CACHE_DATA = disk_data
                _UPDATE_CACHE_TS = disk_ts or now

        if _UPDATE_CACHE_DATA and max_age > 0 and (now - _UPDATE_CACHE_TS) <= max_age:
            return dict(_UPDATE_CACHE_DATA)

    fresh = get_update_info(refresh_remote=refresh_remote)
    with _UPDATE_CACHE_LOCK:
        _set_update_info_cache(fresh, now)
    return fresh


def _state_response(
    state: dict[str, Any],
    *,
    running: bool,
    container_name: str,
    logs: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "action": state.get("action", ACTION_UPDATE),
        "mode": state.get("mode", REINSTALL_MODE_PRESERVE),
        "running": running,
        "status": status or state.get("status", "idle"),
        "container_name": container_name,
        "branch": state.get("branch", ""),
        "target": state.get("target", TARGET_CURRENT),
        "target_ref": state.get("target_ref", ""),
        "with_backup": bool(state.get("with_backup", True)),
        "backup_path": state.get("backup_path", ""),
        "started_at": state.get("started_at", ""),
        "finished_at": state.get("finished_at", ""),
        "exit_code": state.get("exit_code"),
        "logs": state.get("logs", "") if logs is None else logs,
        "error": state.get("error", ""),
    }


def get_update_status(log_lines: int = 200) -> dict[str, Any]:
    state = _load_state()
    container_name = state.get("container_name", "")
    if not container_name:
        return _state_response(state, running=False, container_name="", status="idle")

    inspect_code, inspect_body = _docker_request(
        "GET",
        f"/containers/{_docker_name(container_name)}/json",
        timeout=10,
    )
    if inspect_code == 404:
        state.update(
            {
                "running": False,
                "status": "missing",
                "error": inspect_body or f"container '{container_name}' not found",
            }
        )
        _save_state(state)
        return _state_response(
            state,
            running=False,
            container_name=container_name,
            status="missing",
        )
    if inspect_code >= 400:
        raise RuntimeError(_docker_error_text(inspect_code, inspect_body))

    info = json.loads(inspect_body or "{}")
    st = info.get("State") or {}
    status = (st.get("Status") or "unknown").strip().lower()
    exit_code = st.get("ExitCode")
    started_at = st.get("StartedAt") or ""
    finished_at = st.get("FinishedAt") or ""
    running = status in {"running", "created", "restarting"}

    tail = max(1, min(int(log_lines), 2000))
    logs_code, logs_body = _docker_request(
        "GET",
        f"/containers/{_docker_name(container_name)}/logs?stdout=1&stderr=1&tail={tail}",
        timeout=15,
    )
    logs = logs_body if logs_code < 400 else _docker_error_text(logs_code, logs_body)

    state.update(
        {
            "running": running,
            "status": status,
            "exit_code": exit_code,
            "started_at": started_at or state.get("started_at", ""),
            "finished_at": finished_at if not running else "",
            "logs": logs,
            "error": state.get("error", ""),
        }
    )
    _save_state(state)
    return _state_response(
        state,
        running=running,
        container_name=container_name,
        logs=logs,
        status=status,
    )


def _normalize_target(target: str | None) -> str:
    value = (target or "").strip().lower()
    if not value:
        return TARGET_CURRENT
    if value not in TARGETS:
        raise RuntimeError(f"Invalid target: {target}")
    return value


def _normalize_ref(ref: str | None) -> str:
    value = (ref or "").strip()
    if not value:
        raise RuntimeError("ref is required for custom target")
    if not REF_RE.match(value):
        raise RuntimeError("Invalid ref")
    return value


def _normalize_backup_path(path: str | None, *, required: bool) -> str:
    """
    Resolve a backup archive path for maintenance jobs.
    If `required=True` and path is missing, create a preflight backup automatically.
    """
    if not required:
        if not path or not path.strip():
            return ""
        raw = path.strip()
    else:
        if not path or not path.strip():
            backup_file = create_backup_file(prefix="preflight_backup")
            return str(backup_file)
        raw = path.strip()

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (PROJECT_DIR / candidate).resolve()
    else:
        candidate = candidate.resolve()

    root = BACKUP_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise RuntimeError(f"backup_path must be inside {root}")
    if candidate.suffix.lower() != ".zip":
        raise RuntimeError("backup_path must point to a .zip file")
    if not candidate.exists() or not candidate.is_file():
        raise RuntimeError(f"backup_path not found: {candidate}")
    return str(candidate)


def _start_job(
    *,
    action: str,
    inner_cmd: str,
    branch: str = "",
    mode: str = "",
    target: str = TARGET_CURRENT,
    target_ref: str = "",
    with_backup: bool = True,
    backup_path: str = "",
    actor: str = "",
) -> dict[str, Any]:
    current = get_update_status(log_lines=50)
    if current.get("running"):
        running_action = current.get("action") or ACTION_UPDATE
        raise RuntimeError(f"{running_action} job is already running")

    container_name = f"sbui_{action}_{int(time.time())}"
    final_inner_cmd = (
        f"mkdir -p {shlex.quote(BACKUP_HOME)} && "
        f"export HOME={shlex.quote(BACKUP_HOME)} && "
        f"{inner_cmd}"
    )

    binds = [
        f"{PROJECT_DIR}:/opt/singbox-ui-bot",
        "/var/run/docker.sock:/var/run/docker.sock",
    ]
    project_root = PROJECT_DIR.resolve()
    backup_root = BACKUP_ROOT.resolve()
    if backup_root != project_root and project_root not in backup_root.parents:
        binds.append(f"{backup_root}:{backup_root}")

    create_body = {
        "Image": RUNNER_IMAGE,
        "Cmd": ["bash", "-lc", final_inner_cmd],
        "WorkingDir": "/opt/singbox-ui-bot",
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": True,
        "HostConfig": {"Binds": binds},
    }

    create_code, create_out = _docker_request(
        "POST",
        f"/containers/create?name={_docker_name(container_name)}",
        body=create_body,
        timeout=20,
    )
    if create_code >= 400:
        text = _docker_error_text(create_code, create_out)
        if "No such image" in text and RUNNER_IMAGE in text:
            raise RuntimeError(
                f"Runner image {RUNNER_IMAGE} not found. Rebuild app image first: "
                "cd /opt/singbox-ui-bot && docker compose up -d --build app"
            )
        raise RuntimeError(text)

    created = json.loads(create_out or "{}")
    container_id = (created.get("Id") or "").strip()
    if not container_id:
        raise RuntimeError("Docker API did not return container ID")

    start_code, start_out = _docker_request(
        "POST",
        f"/containers/{_docker_name(container_id)}/start",
        timeout=20,
    )
    if start_code >= 400:
        _docker_request("DELETE", f"/containers/{_docker_name(container_id)}?force=1", timeout=10)
        raise RuntimeError(_docker_error_text(start_code, start_out))

    state = {
        "action": action,
        "mode": mode or REINSTALL_MODE_PRESERVE,
        "running": True,
        "status": "created",
        "container_name": container_name,
        "container_id": container_id,
        "branch": branch,
        "target": target,
        "target_ref": target_ref,
        "with_backup": with_backup,
        "backup_path": backup_path,
        "started_at": datetime_utc_iso(),
        "finished_at": "",
        "exit_code": None,
        "logs": "",
        "error": "",
        "requested_by": actor,
    }
    _save_state(state)
    return {
        "started": True,
        "action": action,
        "mode": mode or REINSTALL_MODE_PRESERVE,
        "container_name": container_name,
        "container_id": container_id,
        "branch": branch,
        "target": target,
        "target_ref": target_ref,
        "with_backup": with_backup,
        "backup_path": backup_path,
    }


def start_update(
    *,
    actor: str = "",
    backup_path: str | None = None,
    target: str = TARGET_LATEST_TAG,
    ref: str | None = None,
    with_backup: bool = True,
    branch: str | None = None,
) -> dict[str, Any]:
    # backward-compatible input: branch=<name> maps to custom ref update
    if branch and not ref:
        target = TARGET_CUSTOM
        ref = branch

    target_mode = _normalize_target(target)
    if target_mode == TARGET_CURRENT:
        target_mode = TARGET_LATEST_TAG

    requested_ref = "latest-tag" if target_mode == TARGET_LATEST_TAG else _normalize_ref(ref)
    backup_enabled = bool(with_backup)
    backup_file = _normalize_backup_path(backup_path, required=backup_enabled)

    env_prefix = [
        f"UPDATE_WITH_BACKUP={'1' if backup_enabled else '0'}",
        "DELETE_BACKUP_AFTER=1",
    ]
    if backup_file:
        env_prefix.append(f"BACKUP_FILE_OVERRIDE={shlex.quote(backup_file)}")
    env_block = " ".join(env_prefix)

    return _start_job(
        action=ACTION_UPDATE,
        inner_cmd=f"printf 'y\\n' | {env_block} bash scripts/manage.sh update {shlex.quote(requested_ref)}",
        branch=_git_value("rev-parse", "--abbrev-ref", "HEAD", default="main"),
        mode=REINSTALL_MODE_PRESERVE,
        target=target_mode,
        target_ref=requested_ref,
        with_backup=backup_enabled,
        backup_path=backup_file,
        actor=actor,
    )


def start_reinstall(
    *,
    actor: str = "",
    clean: bool = True,
    backup_path: str | None = None,
    with_backup: bool = True,
    target: str = TARGET_CURRENT,
    ref: str | None = None,
) -> dict[str, Any]:
    target_mode = _normalize_target(target)
    requested_ref = {
        TARGET_CURRENT: "current",
        TARGET_LATEST_TAG: "latest-tag",
    }.get(target_mode, "")
    if not requested_ref:
        requested_ref = _normalize_ref(ref)

    backup_enabled = bool(with_backup)
    backup_file = _normalize_backup_path(backup_path, required=backup_enabled)
    mode = REINSTALL_MODE_CLEAN if clean else REINSTALL_MODE_PRESERVE

    env_prefix = [
        f"REINSTALL_WITH_BACKUP={'1' if backup_enabled else '0'}",
        f"REINSTALL_CLEAN={'1' if clean else '0'}",
        "DELETE_BACKUP_AFTER=1",
    ]
    if backup_file:
        env_prefix.append(f"BACKUP_FILE_OVERRIDE={shlex.quote(backup_file)}")
    env_block = " ".join(env_prefix)

    return _start_job(
        action=ACTION_REINSTALL,
        inner_cmd=f"printf 'y\\n' | {env_block} bash scripts/manage.sh reinstall {shlex.quote(requested_ref)}",
        branch=_git_value("rev-parse", "--abbrev-ref", "HEAD", default="main"),
        mode=mode,
        target=target_mode,
        target_ref=requested_ref,
        with_backup=backup_enabled,
        backup_path=backup_file,
        actor=actor,
    )


def cleanup_update_job() -> dict[str, Any]:
    state = _load_state()
    container_name = state.get("container_name", "")
    if not container_name:
        return {"removed": False, "detail": "No maintenance job found"}

    status = get_update_status(log_lines=50)
    if status.get("running"):
        raise RuntimeError("Cannot cleanup while maintenance job is running")

    _docker_request("DELETE", f"/containers/{_docker_name(container_name)}?force=1", timeout=15)
    state["container_name"] = ""
    state["container_id"] = ""
    state["running"] = False
    state["status"] = "cleaned"
    _save_state(state)
    return {"removed": True, "container_name": container_name}


def datetime_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
