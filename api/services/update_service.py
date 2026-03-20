"""
Update service:
- Reads git/branch/tag update information from the project repo
- Starts update/reinstall jobs in a detached helper container
- Tracks last job state and returns logs
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import time
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

ACTION_UPDATE = "update"
ACTION_REINSTALL = "reinstall"
REINSTALL_MODE_PRESERVE = "preserve"
REINSTALL_MODE_CLEAN = "clean"


def _resolve_tool(name: str) -> str:
    """Resolve docker/docker-compose paths even when PATH is limited."""
    found = shutil.which(name)
    if found:
        return found
    if name == "docker":
        for candidate in ("/usr/bin/docker", "/usr/local/bin/docker", "/bin/docker"):
            if Path(candidate).exists():
                return candidate
    if name == "docker-compose":
        for candidate in (
            "/usr/bin/docker-compose",
            "/usr/local/bin/docker-compose",
            "/bin/docker-compose",
        ):
            if Path(candidate).exists():
                return candidate
    return name


def _normalize_cmd(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    head = cmd[0]
    if head in {"docker", "docker-compose"}:
        return [_resolve_tool(head), *cmd[1:]]
    return cmd


def _missing_tool_hint(cmd: list[str]) -> str:
    tool = (cmd[0] if cmd else "").strip()
    if tool in {"docker", "/usr/bin/docker", "/usr/local/bin/docker", "/bin/docker", "docker-compose"}:
        return (
            "Docker CLI недоступен внутри app-контейнера.\n"
            "Один раз пересоберите app на хосте и повторите:\n"
            "cd /opt/singbox-ui-bot && docker compose up -d --build app"
        )
    return ""


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str]:
    cmd = _normalize_cmd(cmd)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        hint = _missing_tool_hint(cmd)
        return 1, f"{e}\n{hint}".strip()
    except Exception as e:
        hint = _missing_tool_hint(cmd)
        if hint:
            return 1, f"{e}\n{hint}".strip()
        return 1, str(e)
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


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
    # Keep stable order but de-duplicate
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

    code, inspect = _run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}}|{{.State.ExitCode}}|{{.State.StartedAt}}|{{.State.FinishedAt}}",
            container_name,
        ],
        timeout=10,
    )
    if code != 0:
        state.update(
            {
                "running": False,
                "status": "missing",
                "error": inspect or f"container '{container_name}' not found",
            }
        )
        _save_state(state)
        return _state_response(
            state,
            running=False,
            container_name=container_name,
            status="missing",
        )

    parts = inspect.split("|")
    status = parts[0] if len(parts) > 0 else "unknown"
    exit_code = None
    if len(parts) > 1:
        try:
            exit_code = int(parts[1])
        except Exception:
            exit_code = None
    started_at = parts[2] if len(parts) > 2 else ""
    finished_at = parts[3] if len(parts) > 3 else ""
    running = status in {"running", "created", "restarting"}

    _, logs = _run(["docker", "logs", "--tail", str(log_lines), container_name], timeout=15)
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
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "-v",
        f"{PROJECT_DIR}:/opt/singbox-ui-bot",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-w",
        "/opt/singbox-ui-bot",
        RUNNER_IMAGE,
        "bash",
        "-lc",
        final_inner_cmd,
    ]
    code, out = _run(cmd, timeout=20)
    if code != 0:
        raise RuntimeError(out or f"Failed to start {action} container")

    state = {
        "action": action,
        "mode": mode or REINSTALL_MODE_PRESERVE,
        "running": True,
        "status": "created",
        "container_name": container_name,
        "container_id": out.strip(),
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
        "container_id": out.strip(),
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
        # Clean reinstall = wipe runtime state and recreate stack from repository files.
        # .env is intentionally preserved so connectivity credentials remain intact.
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
            "rm -f -- nginx/.web_ui_enabled nginx/.site_enabled nginx/.banned_ips.json; "
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
        # Reinstall with сохранением = recreate containers without wiping project state.
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

    _run(["docker", "rm", "-f", container_name], timeout=15)
    state["container_name"] = ""
    state["container_id"] = ""
    state["running"] = False
    state["status"] = "cleaned"
    _save_state(state)
    return {"removed": True, "container_name": container_name}


def datetime_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
