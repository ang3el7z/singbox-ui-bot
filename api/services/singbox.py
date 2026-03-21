"""
SingBoxService — direct management of sing-box config.json.

No s-ui, no intermediate API.
Config is a JSON file mounted at SINGBOX_CONFIG_PATH (/etc/sing-box/config.json).
Reload via: docker exec singbox_core sing-box reload
or:         systemctl reload sing-box  (systemd mode)
"""
import asyncio
import json
import uuid as uuid_lib
from pathlib import Path
from typing import Any, Optional

from api.config import settings
from api.services import docker_engine


class SingBoxError(Exception):
    pass


class SingBoxService:
    _BUILTIN_OUTBOUND_PRESETS: dict[str, dict[str, Any]] = {
        "direct": {"type": "direct", "tag": "direct"},
        "block": {"type": "block", "tag": "block"},
        # Secret-Box style WARP detour: local Cloudflare WARP SOCKS proxy.
        "warp": {
            "type": "socks",
            "tag": "warp",
            "server": "127.0.0.1",
            "server_port": 40000,
        },
    }
    _CONTAINER_ALIASES = ("singbox_core", "singbox_sui")
    _SERVICE_HINTS = {"singbox", "sui"}
    _EXCLUDED_NAME_HINTS = ("app", "nginx", "adguard")

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

    def _candidate_container_names(self) -> list[str]:
        seen = set()
        names: list[str] = []
        for raw in [settings.singbox_container, *self._CONTAINER_ALIASES]:
            name = (raw or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def _resolve_container(self) -> tuple[Optional[str], str]:
        configured = (settings.singbox_container or "").strip()

        for name in self._candidate_container_names():
            try:
                docker_engine.inspect_container(name, timeout=5)
                if configured and name != configured:
                    return name, (
                        f"Configured SINGBOX_CONTAINER='{configured}', "
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
            if service in self._SERVICE_HINTS:
                score += 120
            if any(n in self._CONTAINER_ALIASES for n in names):
                score += 100
            if any("singbox" in n for n in names_lower):
                score += 45
            if "sing-box" in image or "singbox" in image:
                score += 60
            if "s-ui" in image:
                score += 40
            if any(hint in name_blob for hint in self._EXCLUDED_NAME_HINTS):
                score -= 120
            if state == "running":
                score += 10

            if score > best_score:
                best_score = score
                best_name = names[0]

        if best_name and best_score > 0:
            if configured and best_name != configured:
                warning = (
                    f"Configured SINGBOX_CONTAINER='{configured}', "
                    f"using detected '{best_name}'."
                )
            else:
                warning = ""
            return best_name, warning

        missing = configured or "<empty>"
        return None, f"Sing-Box container '{missing}' not found."

    async def reload(self) -> bool:
        result = await self.reload_verbose()
        return bool(result.get("success"))

    async def reload_verbose(self) -> dict[str, Any]:
        """Reload sing-box gracefully (no connection drop for existing users)."""
        configured = (settings.singbox_container or "").strip()
        container, warning = await asyncio.to_thread(self._resolve_container)
        if not container:
            return {
                "success": False,
                "container": configured,
                "resolved_container": None,
                "error": warning or "Sing-Box container is not available.",
            }

        ok, out = await self._exec(["sing-box", "reload", "-c", str(self.config_path)])
        if ok:
            result: dict[str, Any] = {
                "success": True,
                "container": configured,
                "resolved_container": container,
            }
            if warning:
                result["warning"] = warning
            return result

        local_error = (out or "").strip()
        hup_error = ""
        try:
            ok2, out2 = await asyncio.to_thread(
                docker_engine.exec_in_container,
                container,
                ["kill", "-HUP", "1"],
                timeout=20,
            )
            if ok2:
                result = {
                    "success": True,
                    "container": configured,
                    "resolved_container": container,
                }
                if warning:
                    result["warning"] = warning
                if local_error:
                    result["note"] = f"local reload failed, docker HUP succeeded: {local_error}"
                return result
            hup_error = (out2 or "").strip() or "docker exec returned non-zero exit code"
        except Exception as e:
            hup_error = str(e).strip() or "docker exec failed"

        errors = []
        if warning:
            errors.append(warning)
        if local_error:
            errors.append(f"local reload failed: {local_error}")
        if hup_error:
            errors.append(f"container HUP failed: {hup_error}")

        return {
            "success": False,
            "container": configured,
            "resolved_container": container,
            "error": "; ".join(errors) or "Reload failed.",
        }

    async def restart(self) -> bool:
        result = await self.restart_verbose()
        return bool(result.get("success"))

    async def restart_verbose(self) -> dict[str, Any]:
        configured = (settings.singbox_container or "").strip()
        container, warning = await asyncio.to_thread(self._resolve_container)
        if not container:
            return {
                "success": False,
                "container": configured,
                "resolved_container": None,
                "error": warning or "Sing-Box container is not available.",
            }

        try:
            await asyncio.to_thread(
                docker_engine.restart_container,
                container,
                timeout=30,
            )
            result: dict[str, Any] = {
                "success": True,
                "container": configured,
                "resolved_container": container,
            }
            if warning:
                result["warning"] = warning
            return result
        except Exception as e:
            error_text = str(e).strip() or "Restart failed."
            if warning:
                error_text = f"{warning}; {error_text}"
            return {
                "success": False,
                "container": configured,
                "resolved_container": container,
                "error": error_text,
            }

    async def get_status(self) -> dict:
        configured = (settings.singbox_container or "").strip()
        container, warning = await asyncio.to_thread(self._resolve_container)
        if not container:
            return {
                "running": False,
                "status": "missing",
                "container": configured,
                "resolved_container": None,
                "error": warning or "Sing-Box container is not available.",
            }

        try:
            info = await asyncio.to_thread(
                docker_engine.inspect_container,
                container,
                timeout=10,
            )
            status_text = str((info.get("State") or {}).get("Status") or "unknown")
            result: dict[str, Any] = {
                "running": status_text == "running",
                "status": status_text,
                "container": configured,
                "resolved_container": container,
            }
            if warning:
                result["warning"] = warning
            return result
        except Exception as e:
            error_text = str(e).strip() or "Status check failed."
            if warning:
                error_text = f"{warning}; {error_text}"
            return {
                "running": False,
                "status": "error",
                "container": configured,
                "resolved_container": container,
                "error": error_text,
            }

    async def get_logs(self, lines: int = 100) -> list[str]:
        result = await self.get_logs_verbose(lines=lines)
        return result.get("logs", [])

    async def get_logs_verbose(self, lines: int = 100) -> dict[str, Any]:
        configured = (settings.singbox_container or "").strip()
        container, warning = await asyncio.to_thread(self._resolve_container)
        if not container:
            return {
                "logs": [],
                "container": configured,
                "resolved_container": None,
                "error": warning or "Sing-Box container is not available.",
            }

        try:
            out = await asyncio.to_thread(
                docker_engine.get_container_logs,
                container,
                tail=lines,
                timeout=15,
            )
            result: dict[str, Any] = {
                "logs": out.splitlines(),
                "container": configured,
                "resolved_container": container,
            }
            if warning:
                result["warning"] = warning
            return result
        except Exception as e:
            error_text = str(e).strip() or "Log fetch failed."
            if warning:
                error_text = f"{warning}; {error_text}"
            return {
                "logs": [],
                "container": configured,
                "resolved_container": container,
                "error": error_text,
            }

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

    # Fields that are our own metadata and must not be written into sing-box config.json
    _INBOUND_META_FIELDS = {"subscribe_port", "subscribe_tls"}

    def save_inbound(self, inbound: dict) -> None:
        """
        Add or replace inbound by tag in sing-box config.json.
        Strips internal metadata fields (subscribe_port, subscribe_tls) before writing —
        sing-box does not understand them and would fail to start.
        """
        cfg = self.read_config()
        inbounds = cfg.setdefault("inbounds", [])
        tag = inbound["tag"]
        # Strip metadata before writing to sing-box config
        sb_inbound = {k: v for k, v in inbound.items() if k not in self._INBOUND_META_FIELDS}
        existing = next((i for i, ib in enumerate(inbounds) if ib.get("tag") == tag), None)
        if existing is not None:
            inbounds[existing] = sb_inbound
        else:
            inbounds.append(sb_inbound)
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

    def add_route_rule(
        self,
        rule_key: str,
        value: str,
        outbound: str,
        download_detour: str = "direct",
        update_interval: str = "1d",
    ) -> None:
        """
        Add one or more routing rules.

        For domain/domain_suffix/domain_keyword/ip_cidr, `value` may be
        comma-separated (e.g. "youtube.com, youtu.be, ytimg.com").
        Each item is added individually into the shared rule array for that outbound.

        For rule_set, `value` is a single URL (the .srs or source JSON URL).
        A rule_set entry is created and referenced from a routing rule pointing to `outbound`.
        `download_detour` and `update_interval` are used only for rule_set.
        """
        cfg = self.read_config()
        route = cfg.setdefault("route", {})
        rules = route.setdefault("rules", [])

        if rule_key == "rule_set":
            rule_sets = route.setdefault("rule_set", [])
            url = value.strip()
            # Use URL hash as stable tag to avoid duplicates on re-add
            import hashlib
            tag = "custom_" + hashlib.md5(url.encode()).hexdigest()[:8]
            if not any(rs["tag"] == tag for rs in rule_sets):
                rule_sets.append({
                    "tag": tag,
                    "type": "remote",
                    "format": "binary" if url.endswith(".srs") else "source",
                    "url": url,
                    "download_detour": download_detour,
                    "update_interval": update_interval,
                })
            target = self._find_or_create_rule(rules, outbound, "rule_set")
            if tag not in target["rule_set"]:
                target["rule_set"].append(tag)
        else:
            # Split comma-separated values, strip whitespace, deduplicate
            values = [v.strip() for v in value.split(",") if v.strip()]
            target = self._find_or_create_rule(rules, outbound, rule_key)
            for v in values:
                if v not in target[rule_key]:
                    target[rule_key].append(v)

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

    def upsert_auth_user_route(self, auth_user: str, outbound: str) -> None:
        """
        Route all traffic for a specific authenticated inbound user to `outbound`.

        Used by federation bridges on intermediate nodes, where traffic for the
        dedicated bridge client must always continue to the next hop.
        """
        cfg = self.read_config()
        route = cfg.setdefault("route", {})
        rules = route.setdefault("rules", [])

        for rule in rules:
            if rule.get("outbound") != outbound:
                continue
            users = rule.get("auth_user")
            if isinstance(users, list):
                if auth_user not in users:
                    users.append(auth_user)
                    self.write_config(cfg)
                return

        rule = {"auth_user": [auth_user], "outbound": outbound}
        rules.insert(self._bridge_rule_insert_index(rules), rule)
        self.write_config(cfg)

    def remove_auth_user_route(self, auth_user: str, outbound: Optional[str] = None) -> bool:
        cfg = self.read_config()
        route = cfg.setdefault("route", {})
        rules = route.setdefault("rules", [])
        removed = False
        new_rules = []

        for rule in rules:
            users = rule.get("auth_user")
            if not isinstance(users, list):
                new_rules.append(rule)
                continue
            if outbound is not None and rule.get("outbound") != outbound:
                new_rules.append(rule)
                continue
            if auth_user not in users:
                new_rules.append(rule)
                continue

            users = [u for u in users if u != auth_user]
            removed = True
            if users:
                rule["auth_user"] = users
                new_rules.append(rule)

        if removed:
            route["rules"] = new_rules
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

    def _bridge_rule_insert_index(self, rules: list[dict]) -> int:
        """
        Insert federation bridge rules after the built-in system rules
        (sniff, DNS hijack, private IP direct), but before user-defined rules.
        """
        idx = 0
        while idx < len(rules):
            rule = rules[idx]
            if rule.get("action") == "sniff":
                idx += 1
                continue
            if rule.get("protocol") == "dns":
                idx += 1
                continue
            if rule.get("ip_is_private") is True:
                idx += 1
                continue
            break
        return idx

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

    def ensure_builtin_outbound(self, tag: str) -> bool:
        """
        Ensure a known built-in outbound exists in config.
        Returns True if config was changed.
        """
        preset = self._BUILTIN_OUTBOUND_PRESETS.get(tag)
        if not preset:
            return False

        cfg = self.read_config()
        outbounds = cfg.setdefault("outbounds", [])
        if any(ob.get("tag") == tag for ob in outbounds):
            return False

        outbounds.append(dict(preset))
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

    # ─── Subscription template injection ──────────────────────────────────────

    def inject_proxy_into_template(self, template_json: str, proxy_ob: dict) -> dict:
        """
        Load a template JSON and replace the placeholder outbound
        ({"tag": "proxy", "type": "__proxy__"}) with the real proxy outbound.
        If no placeholder is found, prepend the proxy outbound to the list.
        """
        import json as _json
        config = _json.loads(template_json)
        outbounds = config.get("outbounds", [])
        injected = False
        for i, ob in enumerate(outbounds):
            if ob.get("type") == "__proxy__":
                outbounds[i] = proxy_ob
                injected = True
                break
        if not injected:
            config["outbounds"] = [proxy_ob] + outbounds
        else:
            config["outbounds"] = outbounds
        return config

    def inject_dns_url(self, config: dict, dns_url: str) -> dict:
        """
        Replace "__dns_url__" placeholder in DNS server addresses with the real DoH URL.
        This injects the per-user AdGuard DoH URL into the client config.
        """
        import json as _json
        # Serialize → replace → deserialize (handles nested structures safely)
        raw = _json.dumps(config, ensure_ascii=False)
        raw = raw.replace('"__dns_url__"', _json.dumps(dns_url))
        return _json.loads(raw)

    def _build_outbound(self, client_data: dict, inbound: dict, domain: str) -> dict:
        """
        Build the client-side proxy outbound from server inbound settings.

        Key fields from the inbound:
          listen_port    — internal sing-box port
          subscribe_port — public port clients connect to (e.g. 443 via Nginx). Falls back to listen_port.
          subscribe_tls  — if True, add TLS to outbound even if inbound has no TLS (Nginx terminates it).
          tls            — inbound TLS settings (Reality, plain TLS, etc.)
          transport      — WS/gRPC/etc.

        For WS protocols fronted by Nginx:
          Nginx listens on subscribe_port (443) → TLS terminated → proxies to sing-box listen_port.
          Client must connect to domain:443 with TLS, even though sing-box inbound has no TLS.
        """
        proto = inbound.get("type", "vless")
        tls = inbound.get("tls", {})
        transport = inbound.get("transport", {})

        # subscribe_port overrides listen_port for the client outbound (e.g. Nginx on 443)
        port = inbound.get("subscribe_port") or inbound.get("listen_port", 443)

        # subscribe_tls forces TLS in the client outbound (used when Nginx terminates TLS)
        force_tls = inbound.get("subscribe_tls", False)

        ob: dict = {
            "tag": "proxy",
            "type": proto,
            "server": domain,
            "server_port": port,
        }

        if proto == "vless":
            ob["uuid"] = client_data.get("uuid", "")
            reality = tls.get("reality", {})
            if reality.get("enabled"):
                # VLESS + Reality: flow required, custom TLS fingerprint
                ob["flow"] = "xtls-rprx-vision"
                ob["tls"] = {
                    "enabled": True,
                    "server_name": tls.get("server_name", domain),
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                    "reality": {
                        "enabled": True,
                        "public_key": reality.get("public_key", ""),
                        "short_id": (reality.get("short_id") or [""])[0],
                    },
                }
            elif tls.get("enabled") or force_tls:
                # VLESS + plain TLS (or Nginx-fronted WS)
                ob["tls"] = {"enabled": True, "server_name": domain}
            if transport.get("type") == "ws":
                ob["transport"] = {"type": "ws", "path": transport.get("path", "/")}

        elif proto == "vmess":
            ob["uuid"] = client_data.get("uuid", "")
            ob["alter_id"] = 0
            if tls.get("enabled") or force_tls:
                ob["tls"] = {"enabled": True, "server_name": domain}
            if transport.get("type") == "ws":
                ob["transport"] = {"type": "ws", "path": transport.get("path", "/")}

        elif proto == "trojan":
            ob["password"] = client_data.get("password", "")
            # Trojan always uses TLS
            ob["tls"] = {"enabled": True, "server_name": domain}
            if transport.get("type") == "ws":
                ob["transport"] = {"type": "ws", "path": transport.get("path", "/")}

        elif proto == "shadowsocks":
            ob["method"] = inbound.get("method", "aes-256-gcm")
            ob["password"] = client_data.get("password", "")

        elif proto == "hysteria2":
            ob["password"] = client_data.get("password", "")
            ob["tls"] = {"enabled": True, "server_name": domain}

        elif proto == "tuic":
            ob["uuid"] = client_data.get("uuid", "")
            ob["password"] = client_data.get("password", "")
            ob["tls"] = {"enabled": True, "server_name": domain}
            ob["congestion_control"] = "bbr"

        return ob

    def build_client_config(
        self,
        client_data: dict,
        inbound: dict,
        template_json: str,
        sub_id: str = "",
    ) -> dict:
        """
        Build a client-side sing-box config by injecting:
          1. The proxy outbound (replaces {"tag":"proxy","type":"__proxy__"})
          2. The per-user AdGuard DoH URL (replaces "__dns_url__" in DNS server addresses)

        template_json — JSON string with the two placeholders.
        sub_id        — subscription ID used to build the per-user DoH URL.
        """
        from api.routers.settings_router import get_runtime
        from api.services.nginx_service import get_doh_url

        domain = get_runtime("domain")
        proxy_ob = self._build_outbound(client_data, inbound, domain)
        config = self.inject_proxy_into_template(template_json, proxy_ob)

        # Inject per-user AdGuard DoH URL if domain and sub_id are available
        if domain and sub_id:
            dns_url = get_doh_url(sub_id, domain)
            config = self.inject_dns_url(config, dns_url)
        else:
            # Fallback: replace placeholder with Cloudflare DoH so config is still valid
            config = self.inject_dns_url(config, "https://cloudflare-dns.com/dns-query")

        return config

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
