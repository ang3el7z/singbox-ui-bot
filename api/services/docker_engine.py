"""
Docker Engine API helpers (unix socket, no docker CLI dependency).
"""
from __future__ import annotations

import http.client
import json
import socket
from pathlib import Path
from typing import Any
from urllib.parse import quote


DOCKER_SOCK = Path("/var/run/docker.sock")


class DockerAPIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: int = 30):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def _name(value: str) -> str:
    return quote(value, safe="")


def _error_text(status: int, body: str) -> str:
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


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> tuple[int, str]:
    if not DOCKER_SOCK.exists():
        raise DockerAPIError(
            "Docker socket is not mounted inside app container (expected /var/run/docker.sock)."
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
        raise DockerAPIError(f"Docker API request failed: {e}") from e
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _ensure(status: int, body: str, *, allowed: tuple[int, ...]) -> None:
    if status not in allowed:
        raise DockerAPIError(_error_text(status, body), status=status, body=body)


def inspect_container(container: str, *, timeout: int = 10) -> dict[str, Any]:
    status, body = _request("GET", f"/containers/{_name(container)}/json", timeout=timeout)
    _ensure(status, body, allowed=(200,))
    try:
        return json.loads(body or "{}")
    except Exception as e:
        raise DockerAPIError(f"Invalid Docker inspect response for '{container}': {e}") from e


def restart_container(container: str, *, timeout: int = 30) -> None:
    status, body = _request(
        "POST",
        f"/containers/{_name(container)}/restart?t=10",
        timeout=timeout,
    )
    _ensure(status, body, allowed=(204,))


def get_container_logs(container: str, *, tail: int = 100, timeout: int = 15) -> str:
    tail = max(1, min(int(tail), 2000))
    status, body = _request(
        "GET",
        f"/containers/{_name(container)}/logs?stdout=1&stderr=1&tail={tail}",
        timeout=timeout,
    )
    _ensure(status, body, allowed=(200,))
    return body


def exec_in_container(
    container: str,
    cmd: list[str],
    *,
    timeout: int = 30,
    tty: bool = True,
) -> tuple[bool, str]:
    create_body = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": tty,
        "Cmd": cmd,
    }
    create_status, create_out = _request(
        "POST",
        f"/containers/{_name(container)}/exec",
        body=create_body,
        timeout=timeout,
    )
    _ensure(create_status, create_out, allowed=(201,))

    try:
        exec_id = (json.loads(create_out).get("Id") or "").strip()
    except Exception:
        exec_id = ""
    if not exec_id:
        raise DockerAPIError(f"Docker exec ID is missing for '{container}'.")

    start_status, start_out = _request(
        "POST",
        f"/exec/{_name(exec_id)}/start",
        body={"Detach": False, "Tty": tty},
        timeout=timeout,
    )
    _ensure(start_status, start_out, allowed=(200,))

    inspect_status, inspect_out = _request(
        "GET",
        f"/exec/{_name(exec_id)}/json",
        timeout=10,
    )
    _ensure(inspect_status, inspect_out, allowed=(200,))
    try:
        exit_code = json.loads(inspect_out).get("ExitCode")
    except Exception:
        exit_code = None
    return exit_code == 0, (start_out or "").strip()


def run_container_detached(
    *,
    name: str,
    image: str,
    cmd: list[str],
    binds: list[str] | None = None,
    working_dir: str | None = None,
    auto_remove: bool = False,
    tty: bool = True,
    timeout: int = 30,
) -> str:
    create_body: dict[str, Any] = {
        "Image": image,
        "Cmd": cmd,
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": tty,
        "HostConfig": {
            "AutoRemove": auto_remove,
            "Binds": binds or [],
        },
    }
    if working_dir:
        create_body["WorkingDir"] = working_dir

    create_status, create_out = _request(
        "POST",
        f"/containers/create?name={_name(name)}",
        body=create_body,
        timeout=timeout,
    )
    _ensure(create_status, create_out, allowed=(201,))
    try:
        container_id = (json.loads(create_out).get("Id") or "").strip()
    except Exception:
        container_id = ""
    if not container_id:
        raise DockerAPIError("Docker API did not return container ID.")

    start_status, start_out = _request(
        "POST",
        f"/containers/{_name(container_id)}/start",
        timeout=timeout,
    )
    if start_status not in (204,):
        try:
            _request("DELETE", f"/containers/{_name(container_id)}?force=1", timeout=10)
        except Exception:
            pass
        raise DockerAPIError(_error_text(start_status, start_out), status=start_status, body=start_out)

    return container_id


def remove_container_force(container: str, *, timeout: int = 15) -> None:
    status, body = _request(
        "DELETE",
        f"/containers/{_name(container)}?force=1",
        timeout=timeout,
    )
    _ensure(status, body, allowed=(204,))
