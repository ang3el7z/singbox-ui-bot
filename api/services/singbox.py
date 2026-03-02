"""
SingBoxService — direct management of sing-box config.json.

No s-ui, no intermediate API.
Config is a JSON file mounted at SINGBOX_CONFIG_PATH (/etc/sing-box/config.json).
Reload via: docker exec singbox_core sing-box reload
or:         systemctl reload sing-box  (systemd mode)
"""
import asyncio
import json
import subprocess
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

from api.config import settings


class SingBoxError(Exception):
    pass


class SingBoxService:

    @property
    def config_path(self) -> Path:
        return Path(settings.singbox_config_path)

    # ─── Config I/O ───────────────────────────────────────────────────────────

    def read_config(self) -> dict:
        if not self.config_path.exists():
            raise SingBoxError(f"Config not found: {self.config_path}")
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def write_config(self, cfg: dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    async def reload(self) -> bool:
        """Reload sing-box gracefully (no connection drop for existing users)."""
        ok, _ = await self._exec(["sing-box", "reload", "-c", str(self.config_path)])
        if ok:
            return True
        # Fallback: restart container
        ok, _ = await self._exec(["docker", "exec", settings.singbox_container, "kill", "-HUP", "1"])
        return ok

    async def restart(self) -> bool:
        ok, _ = await self._exec(["docker", "restart", settings.singbox_container])
        return ok

    async def get_status(self) -> dict:
        ok, out = await self._exec(["docker", "inspect", "--format", "{{.State.Status}}", settings.singbox_container])
        running = ok and out.strip() == "running"
        return {"running": running, "container": settings.singbox_container}

    async def get_logs(self, lines: int = 100) -> list[str]:
        ok, out = await self._exec(
            ["docker", "logs", "--tail", str(lines), settings.singbox_container],
        )
        return out.splitlines() if ok else []

    async def validate_config(self, cfg: dict) -> tuple[bool, str]:
        """Write to a temp file and validate with sing-box check."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg, f, indent=2)
            tmp = f.name
        try:
            ok, out = await self._exec(["sing-box", "check", "-c", tmp])
            return ok, out
        finally:
            os.unlink(tmp)

    # ─── Inbounds ─────────────────────────────────────────────────────────────

    def get_inbounds(self) -> list[dict]:
        return self.read_config().get("inbounds", [])

    def get_inbound(self, tag: str) -> Optional[dict]:
        return next((ib for ib in self.get_inbounds() if ib.get("tag") == tag), None)

    def save_inbound(self, inbound: dict) -> None:
        """Add or replace inbound by tag."""
        cfg = self.read_config()
        inbounds = cfg.setdefault("inbounds", [])
        tag = inbound["tag"]
        existing = next((i for i, ib in enumerate(inbounds) if ib.get("tag") == tag), None)
        if existing is not None:
            inbounds[existing] = inbound
        else:
            inbounds.append(inbound)
        self.write_config(cfg)

    def delete_inbound(self, tag: str) -> bool:
        cfg = self.read_config()
        inbounds = cfg.get("inbounds", [])
        new = [ib for ib in inbounds if ib.get("tag") != tag]
        if len(new) == len(inbounds):
            return False
        cfg["inbounds"] = new
        # Remove users from this inbound in clients (handled at router level)
        self.write_config(cfg)
        return True

    # ─── Users inside inbounds ────────────────────────────────────────────────

    def get_inbound_users(self, tag: str) -> list[dict]:
        ib = self.get_inbound(tag)
        if not ib:
            return []
        return ib.get("users", [])

    def add_user_to_inbound(self, tag: str, user: dict) -> None:
        """
        user format varies by protocol:
          VLESS/TUIC: {"name": str, "uuid": str}
          VMess:      {"name": str, "uuid": str, "alterId": 0}
          Trojan:     {"name": str, "password": str}
          Shadowsocks: added as separate inbound (one user = one inbound)
          Hysteria2:  {"name": str, "password": str}
        """
        cfg = self.read_config()
        for ib in cfg.get("inbounds", []):
            if ib.get("tag") == tag:
                users = ib.setdefault("users", [])
                # Remove existing user with same name to avoid duplicates
                ib["users"] = [u for u in users if u.get("name") != user.get("name")]
                ib["users"].append(user)
                break
        self.write_config(cfg)

    def remove_user_from_inbound(self, tag: str, name: str) -> bool:
        cfg = self.read_config()
        removed = False
        for ib in cfg.get("inbounds", []):
            if ib.get("tag") == tag:
                before = len(ib.get("users", []))
                ib["users"] = [u for u in ib.get("users", []) if u.get("name") != name]
                removed = len(ib["users"]) < before
                break
        self.write_config(cfg)
        return removed

    def toggle_user_in_inbound(self, tag: str, name: str, enable: bool) -> None:
        cfg = self.read_config()
        for ib in cfg.get("inbounds", []):
            if ib.get("tag") == tag:
                for user in ib.get("users", []):
                    if user.get("name") == name:
                        # sing-box doesn't have a native enable field;
                        # we remove/add the user to simulate enable/disable
                        user["_disabled"] = not enable
                break
        self.write_config(cfg)

    # ─── Routing ──────────────────────────────────────────────────────────────

    def get_route(self) -> dict:
        return self.read_config().get("route", {})

    def save_route(self, route: dict) -> None:
        cfg = self.read_config()
        cfg["route"] = route
        self.write_config(cfg)

    def add_route_rule(self, rule_key: str, value: str, outbound: str) -> None:
        cfg = self.read_config()
        route = cfg.setdefault("route", {})
        rules = route.setdefault("rules", [])

        if rule_key == "rule_set":
            # For rule sets, create a rule_set entry + rule referencing it
            rule_sets = route.setdefault("rule_set", [])
            tag = f"custom_{len(rule_sets)}"
            rule_sets.append({
                "tag": tag,
                "type": "remote",
                "format": "binary" if value.endswith(".srs") else "source",
                "url": value,
                "download_detour": "direct",
            })
            target = self._find_or_create_rule(rules, outbound, "rule_set")
            target["rule_set"].append(tag)
        else:
            target = self._find_or_create_rule(rules, outbound, rule_key)
            if value not in target[rule_key]:
                target[rule_key].append(value)

        self.write_config(cfg)

    def remove_route_rule(self, rule_key: str, value: str) -> bool:
        cfg = self.read_config()
        route = cfg.setdefault("route", {})
        rules = route.setdefault("rules", [])
        removed = False
        for rule in rules:
            if rule_key in rule and value in rule[rule_key]:
                rule[rule_key].remove(value)
                removed = True
                if not rule[rule_key]:
                    rules.remove(rule)
                break
        self.write_config(cfg)
        return removed

    def get_route_rules(self, rule_key: str) -> list[tuple[str, str]]:
        """Return list of (value, outbound) for a given rule_key."""
        rules = self.get_route().get("rules", [])
        result = []
        for rule in rules:
            if rule_key in rule:
                outbound = rule.get("outbound", "direct")
                for v in rule[rule_key]:
                    result.append((v, outbound))
        return result

    def _find_or_create_rule(self, rules: list, outbound: str, rule_key: str) -> dict:
        for rule in rules:
            if rule.get("outbound") == outbound and rule_key in rule:
                return rule
        new_rule = {"outbound": outbound, rule_key: []}
        rules.append(new_rule)
        return new_rule

    # ─── Outbounds ────────────────────────────────────────────────────────────

    def get_outbounds(self) -> list[dict]:
        return self.read_config().get("outbounds", [])

    def save_outbound(self, outbound: dict) -> None:
        cfg = self.read_config()
        outbounds = cfg.setdefault("outbounds", [])
        tag = outbound["tag"]
        existing = next((i for i, ob in enumerate(outbounds) if ob.get("tag") == tag), None)
        if existing is not None:
            outbounds[existing] = outbound
        else:
            outbounds.append(outbound)
        self.write_config(cfg)

    def delete_outbound(self, tag: str) -> bool:
        cfg = self.read_config()
        outbounds = cfg.get("outbounds", [])
        new = [ob for ob in outbounds if ob.get("tag") != tag]
        if len(new) == len(outbounds):
            return False
        cfg["outbounds"] = new
        self.write_config(cfg)
        return True

    # ─── Key generation ───────────────────────────────────────────────────────

    def generate_uuid(self) -> str:
        return str(uuid_lib.uuid4())

    async def generate_reality_keypair(self) -> dict:
        """Generate Reality key pair using sing-box generate."""
        ok, out = await self._exec(["sing-box", "generate", "reality-keypair"])
        if ok and out:
            lines = out.strip().splitlines()
            kp = {}
            for line in lines:
                if ":" in line:
                    k, v = line.split(":", 1)
                    kp[k.strip().lower().replace(" ", "_")] = v.strip()
            return kp
        return {"private_key": "", "public_key": ""}

    async def generate_short_id(self) -> str:
        ok, out = await self._exec(["sing-box", "generate", "rand", "--hex", "8"])
        return out.strip() if ok else "abcdef01"

    # ─── Subscription ─────────────────────────────────────────────────────────

    def build_client_config(self, client_data: dict, inbound: dict) -> dict:
        """
        Build a client-side sing-box config for a given client + inbound.
        Returns a dict ready to be serialized as JSON.
        """
        from api.routers.settings_router import get_runtime
        domain = get_runtime("domain")

        proto = inbound.get("type", "vless")
        port = inbound.get("listen_port", 443)
        tls = inbound.get("tls", {})
        transport = inbound.get("transport", {})

        outbound: dict = {
            "tag": "proxy",
            "type": proto,
            "server": domain,
            "server_port": port,
        }

        if proto == "vless":
            outbound["uuid"] = client_data.get("uuid", "")
            outbound["flow"] = ""
            if tls.get("enabled"):
                reality = tls.get("reality", {})
                if reality.get("enabled"):
                    outbound["tls"] = {
                        "enabled": True,
                        "server_name": tls.get("server_name", domain),
                        "utls": {"enabled": True, "fingerprint": "chrome"},
                        "reality": {
                            "enabled": True,
                            "public_key": reality.get("public_key", ""),
                            "short_id": reality.get("short_id", [""])[0],
                        },
                    }
                else:
                    outbound["tls"] = {"enabled": True, "server_name": domain}
            if transport.get("type") == "ws":
                outbound["transport"] = {"type": "ws", "path": transport.get("path", "/")}

        elif proto == "trojan":
            outbound["password"] = client_data.get("password", "")
            outbound["tls"] = {"enabled": True, "server_name": domain}
            if transport.get("type") == "ws":
                outbound["transport"] = {"type": "ws", "path": transport.get("path", "/")}

        elif proto == "shadowsocks":
            outbound["method"] = inbound.get("method", "aes-256-gcm")
            outbound["password"] = client_data.get("password", "")

        elif proto == "hysteria2":
            outbound["password"] = client_data.get("password", "")
            outbound["tls"] = {"enabled": True, "server_name": domain}

        elif proto == "tuic":
            outbound["uuid"] = client_data.get("uuid", "")
            outbound["password"] = client_data.get("password", "")
            outbound["tls"] = {"enabled": True, "server_name": domain}
            outbound["congestion_control"] = "bbr"

        return {
            "log": {"level": "info"},
            "inbounds": [
                {"tag": "tun-in", "type": "tun", "address": ["172.19.0.1/30"], "auto_route": True, "sniff": True}
            ],
            "outbounds": [
                outbound,
                {"tag": "direct", "type": "direct"},
                {"tag": "block",  "type": "block"},
            ],
            "route": {"rules": [], "final": "proxy"},
        }

    # ─── Helper ───────────────────────────────────────────────────────────────

    async def _exec(self, cmd: list[str]) -> tuple[bool, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return proc.returncode == 0, stdout.decode(errors="replace")
        except asyncio.TimeoutError:
            return False, "timeout"
        except Exception as e:
            return False, str(e)


# Singleton
singbox = SingBoxService()
