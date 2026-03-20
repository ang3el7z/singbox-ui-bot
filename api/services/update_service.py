"""
Update service:
- Reads git/branch/tag update information from the project repo
- Starts update/reinstall jobs in a detached helper container
- Tracks last job state and returns logs
"""
from __future__ import annotations

import http.client
import json
import re
import shlex
import socket
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any


PROJECT_DIR = Path("/opt/singbox-ui-bot")
if not PROJECT_DIR.exists():
    PROJECT_DIR = Path(__file__).parent.parent.parent

STATE_FILE = Path("/app/data/update_state.json")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

RUNNER_IMAGE = "singbox-ui-bot-app:latest"
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
BACKUP_HOME = "/opt/singbox-ui-bot/data/recovery"
DOCKER_SOCK = Path("/var/run/docker.sock")

ACTION_UPDATE = "update"
ACTION_REINSTALL = "reinstall"
REINSTALL_MODE_PRESERVE = "preserve"
REINSTALL_MODE_CLEAN = "clean"


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


def _git_value(*args: str, default: str = "") -> str:
    code, out = _run(["git", *args], cwd=PROJECT_DIR)
    if code != 0:
        return default
    return out.strip() or default


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
        raise RuntimeError(f"Git repository not found in {PROJECT_DIR}")

    git_error = ""
    if refresh_remote:
        code, out = _run(["git", "fetch", "--tags", "--prune", "origin"], cwd=PROJECT_DIR, timeout=45)
        if code != 0:
            git_error = out or "git fetch failed"

    current_branch = _git_value("rev-parse", "--abbrev-ref", "HEAD", default="main")
    current_commit = _git_value("rev-parse", "--short", "HEAD", default="-")
    current_commit_full = _git_value("rev-parse", "HEAD", default="")
    current_tag = _git_value("describe", "--tags", "--exact-match", default="")

    tags_raw = _git_value("tag", "--sort=-v:refname", default="")
    latest_tag = tags_raw.splitlines()[0].strip() if tags_raw.strip() else ""

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
        "latest_tag": latest_tag,
        "remote_branch_commit": remote_commit_short,
        "update_available_branch": update_available_branch,
        "update_available_tag": update_available_tag,
        "remote_branches": _list_remote_branches(),
        "git_error": git_error,
    }


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


def _normalize_branch(branch: str | None) -> str:
    branch = (branch or "").strip()
    if not branch:
        branch = _git_value("rev-parse", "--abbrev-ref", "HEAD", default="main")
    if not BRANCH_RE.match(branch):
        raise RuntimeError("Invalid branch name")
    return branch


def _start_job(
    *,
    action: str,
    inner_cmd: str,
    branch: str = "",
    mode: str = "",
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

    create_body = {
        "Image": RUNNER_IMAGE,
        "Cmd": ["bash", "-lc", final_inner_cmd],
        "WorkingDir": "/opt/singbox-ui-bot",
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": True,
        "HostConfig": {
            "Binds": [
                f"{PROJECT_DIR}:/opt/singbox-ui-bot",
                "/var/run/docker.sock:/var/run/docker.sock",
            ]
        },
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
    }


def start_update(branch: str | None = None, actor: str = "") -> dict[str, Any]:
    branch = _normalize_branch(branch)
    branch_q = shlex.quote(branch)
    return _start_job(
        action=ACTION_UPDATE,
        inner_cmd=f"printf 'y\\n' | bash scripts/manage.sh update {branch_q}",
        branch=branch,
        mode=REINSTALL_MODE_PRESERVE,
        actor=actor,
    )


def start_reinstall(actor: str = "", clean: bool = False) -> dict[str, Any]:
    branch = _git_value("rev-parse", "--abbrev-ref", "HEAD", default="main")
    mode = REINSTALL_MODE_CLEAN if clean else REINSTALL_MODE_PRESERVE
    if clean:
        inner_cmd = (
            "set -e; "
            "bash scripts/manage.sh backup || true; "
            "if docker compose version >/dev/null 2>&1; then "
            "docker compose down --volumes --remove-orphans; "
            "else "
            "docker-compose down --volumes --remove-orphans; "
            "fi; "
            "rm -rf -- "
            "data/* subs/* configs/* "
            "config/sing-box/* config/adguard/* "
            "nginx/override/* nginx/htpasswd/* nginx/certs/* nginx/certbot/* "
            "nginx/conf.d/* nginx/logs/*; "
            "rm -f -- nginx/.web_ui_enabled nginx/.banned_ips.json; "
            "mkdir -p "
            "data subs configs "
            "config/sing-box config/adguard "
            "nginx/override nginx/htpasswd nginx/certs nginx/certbot nginx/conf.d nginx/logs; "
            "if docker compose version >/dev/null 2>&1; then "
            "docker compose up -d --build; "
            "else "
            "docker-compose up -d --build; "
            "fi"
        )
    else:
        inner_cmd = (
            "set -e; "
            "bash scripts/manage.sh backup || true; "
            "if docker compose version >/dev/null 2>&1; then "
            "docker compose down; "
            "docker compose up -d --build; "
            "else "
            "docker-compose down; "
            "docker-compose up -d --build; "
            "fi"
        )
    return _start_job(
        action=ACTION_REINSTALL,
        inner_cmd=inner_cmd,
        branch=branch,
        mode=mode,
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
