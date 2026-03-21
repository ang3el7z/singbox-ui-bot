"""
WARP control service.

Manages Cloudflare WARP sidecar container and exposes helpers:
  - get_status()
  - turn_on()
  - turn_off()
"""
from __future__ import annotations

import re
from typing import Any, Optional

from api.config import settings
from api.services import docker_engine


class WarpServiceError(Exception):
    pass


class WarpService:
    _CONTAINER_ALIASES = ("singbox_warp", "warp")
    _TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
    _TRACE_SOCKS = "socks5://127.0.0.1:40000"

    def _candidate_container_names(self) -> list[str]:
        seen = set()
        names: list[str] = []
        for raw in [settings.warp_container, *self._CONTAINER_ALIASES]:
            name = (raw or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def _resolve_container(self) -> tuple[Optional[str], str]:
        configured = (settings.warp_container or "").strip()

        for name in self._candidate_container_names():
            try:
                docker_engine.inspect_container(name, timeout=5)
                if configured and name != configured:
                    return name, (
                        f"Configured WARP_CONTAINER='{configured}', "
                        f"using detected '{name}'."
                    )
                return name, ""
            except Exception:
                continue

        try:
            containers = docker_engine.list_containers(all=True, timeout=8)
        except Exception as e:
            msg = str(e).strip() or "cannot list docker containers"
            return None, msg

        best_name = ""
        best_score = -10_000
        for c in containers:
            raw_names = c.get("Names") or []
            if not isinstance(raw_names, list):
                continue
            names = [str(n).lstrip("/") for n in raw_names if str(n).strip()]
            if not names:
                continue

            labels = c.get("Labels") or {}
            if not isinstance(labels, dict):
                labels = {}
            service = str(labels.get("com.docker.compose.service") or "").strip().lower()
            image = str(c.get("Image") or "").strip().lower()
            state = str(c.get("State") or "").strip().lower()
            names_lower = [n.lower() for n in names]
            name_blob = " ".join(names_lower)

            score = 0
            if service == "warp":
                score += 160
            if any("warp" in n for n in names_lower):
                score += 80
            if "warp" in image:
                score += 40
            if state == "running":
                score += 10
            if any(x in name_blob for x in ("app", "nginx", "adguard", "singbox")):
                score -= 80

            if score > best_score:
                best_score = score
                best_name = names[0]

        if best_name and best_score > 0:
            if configured and best_name != configured:
                warning = (
                    f"Configured WARP_CONTAINER='{configured}', "
                    f"using detected '{best_name}'."
                )
            else:
                warning = ""
            return best_name, warning

        missing = configured or "<empty>"
        return None, f"WARP container '{missing}' not found."

    def _exec(self, container: str, cmd: list[str], timeout: int = 45) -> tuple[bool, str]:
        try:
            ok, out = docker_engine.exec_in_container(container, cmd, timeout=timeout, tty=False)
            return ok, (out or "").strip()
        except Exception as e:
            raise WarpServiceError(str(e)) from e

    def _exec_sh(self, container: str, script: str, timeout: int = 45) -> tuple[bool, str]:
        return self._exec(container, ["sh", "-lc", script], timeout=timeout)

    def _run_step(
        self,
        container: str,
        script: str,
        *,
        step: str,
        allow_fail: bool = False,
        timeout: int = 45,
    ) -> str:
        ok, out = self._exec_sh(container, script, timeout=timeout)
        if not ok and not allow_fail:
            detail = out or "unknown error"
            raise WarpServiceError(f"{step} failed: {detail}")
        return out

    @staticmethod
    def _parse_warp_mode(trace: str) -> str:
        match = re.search(r"(?m)^warp=([^\s]+)$", trace or "")
        if not match:
            return "unknown" if (trace or "").strip() else "off"
        return match.group(1).strip().lower()

    def _ensure_container_running(self, container: str) -> None:
        try:
            info = docker_engine.inspect_container(container, timeout=8)
        except Exception as e:
            raise WarpServiceError(str(e)) from e

        state = str((info.get("State") or {}).get("Status") or "").strip().lower()
        if state == "running":
            return

        try:
            docker_engine.restart_container(container, timeout=30)
        except Exception as e:
            raise WarpServiceError(f"Failed to start container '{container}': {e}") from e

    def get_status(self) -> dict[str, Any]:
        configured = (settings.warp_container or "").strip()
        container, warning = self._resolve_container()
        if not container:
            return {
                "available": False,
                "container": configured,
                "resolved_container": None,
                "running": False,
                "service_running": False,
                "warp": "off",
                "proxy_port": 40000,
                "error": warning or "WARP container is not available.",
            }

        try:
            info = docker_engine.inspect_container(container, timeout=10)
        except Exception as e:
            error_text = str(e).strip() or "Status check failed."
            if warning:
                error_text = f"{warning}; {error_text}"
            return {
                "available": True,
                "container": configured,
                "resolved_container": container,
                "running": False,
                "service_running": False,
                "warp": "off",
                "proxy_port": 40000,
                "error": error_text,
            }

        state = str((info.get("State") or {}).get("Status") or "unknown")
        running = state == "running"
        result: dict[str, Any] = {
            "available": True,
            "container": configured,
            "resolved_container": container,
            "running": running,
            "status": state,
            "service_running": False,
            "warp": "off",
            "proxy_port": 40000,
        }
        if warning:
            result["warning"] = warning
        if not running:
            return result

        ok, out = self._exec_sh(container, "pgrep warp-svc >/dev/null && echo on || echo off", timeout=10)
        service_running = ok and out.strip().endswith("on")
        result["service_running"] = service_running
        if not service_running:
            return result

        _, trace = self._exec_sh(
            container,
            f"curl -sS -m 4 -x {self._TRACE_SOCKS} {self._TRACE_URL} || true",
            timeout=12,
        )
        result["warp"] = self._parse_warp_mode(trace)
        if trace.strip():
            result["trace"] = trace.strip()
        return result

    def turn_on(self, license_key: str | None = None) -> dict[str, Any]:
        container, warning = self._resolve_container()
        if not container:
            raise WarpServiceError(warning or "WARP container is not available.")

        self._ensure_container_running(container)

        self._run_step(
            container,
            "pgrep warp-svc >/dev/null || nohup warp-svc >/dev/null 2>&1 &",
            step="start warp-svc",
            timeout=20,
        )
        self._run_step(
            container,
            "for i in 1 2 3 4 5; do pgrep warp-svc >/dev/null && exit 0; sleep 1; done; exit 1",
            step="wait warp-svc",
            timeout=15,
        )

        conf_exists = self._run_step(
            container,
            "test -f /var/lib/cloudflare-warp/conf.json && echo 1 || echo 0",
            step="check registration",
            timeout=10,
        ).strip().endswith("1")

        if not conf_exists:
            self._run_step(
                container,
                "warp-cli --accept-tos registration new",
                step="register warp device",
                timeout=50,
            )

        if license_key:
            safe_key = license_key.replace("'", "'\"'\"'")
            self._run_step(
                container,
                f"warp-cli --accept-tos registration license '{safe_key}'",
                step="apply warp license",
                timeout=40,
            )

        self._run_step(
            container,
            "warp-cli --accept-tos mode proxy",
            step="set proxy mode",
            timeout=20,
        )
        self._run_step(
            container,
            "warp-cli --accept-tos proxy port 40000",
            step="set proxy port",
            timeout=20,
        )
        self._run_step(
            container,
            "warp-cli --accept-tos disconnect || true",
            step="disconnect previous session",
            allow_fail=True,
            timeout=20,
        )
        self._run_step(
            container,
            "warp-cli --accept-tos connect",
            step="connect warp",
            timeout=35,
        )

        return self.get_status()

    def turn_off(self, forget_registration: bool = True) -> dict[str, Any]:
        container, warning = self._resolve_container()
        if not container:
            raise WarpServiceError(warning or "WARP container is not available.")

        self._ensure_container_running(container)

        self._run_step(
            container,
            "warp-cli --accept-tos disconnect || true",
            step="disconnect warp",
            allow_fail=True,
            timeout=20,
        )
        if forget_registration:
            self._run_step(
                container,
                "warp-cli --accept-tos registration delete || true",
                step="delete warp registration",
                allow_fail=True,
                timeout=30,
            )
        self._run_step(
            container,
            "pkill warp-svc || true",
            step="stop warp-svc",
            allow_fail=True,
            timeout=15,
        )

        return self.get_status()


warp_service = WarpService()

