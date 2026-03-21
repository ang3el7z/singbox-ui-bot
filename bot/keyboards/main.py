"""
All bot keyboards. Callback data patterns match bot/handlers/*.
"""
from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.routers.settings_router import get_runtime


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


def kb_back(callback: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_txt("Назад", "Back"), callback_data=callback)]]
    )


def _build(*rows: List[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def kb_main_menu() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("Sing-Box", "Sing-Box"), callback_data="menu_server")],
        [
            InlineKeyboardButton(text=_txt("AdGuard", "AdGuard"), callback_data="menu_adguard"),
            InlineKeyboardButton(text=_txt("Nginx", "Nginx"), callback_data="menu_nginx"),
        ],
        [
            InlineKeyboardButton(text=_txt("WARP", "WARP"), callback_data="menu_warp"),
            InlineKeyboardButton(text=_txt("Federation", "Federation"), callback_data="menu_federation"),
        ],
        [
            InlineKeyboardButton(text=_txt("Templates", "Templates"), callback_data="menu_templates"),
            InlineKeyboardButton(text=_txt("Admins", "Admins"), callback_data="menu_admin"),
        ],
        [
            InlineKeyboardButton(text=_txt("Documentation", "Documentation"), callback_data="menu_docs"),
            InlineKeyboardButton(text=_txt("Maintenance", "Maintenance"), callback_data="menu_maintenance"),
        ],
        [InlineKeyboardButton(text=_txt("Settings", "Settings"), callback_data="menu_settings")],
    )


def kb_server() -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=_txt("Status", "Status"), callback_data="server_status"),
            InlineKeyboardButton(text=_txt("Logs", "Logs"), callback_data="server_logs"),
        ],
        [
            InlineKeyboardButton(text=_txt("Reload", "Reload"), callback_data="server_reload"),
            InlineKeyboardButton(text=_txt("Restart", "Restart"), callback_data="server_restart"),
        ],
        [InlineKeyboardButton(text=_txt("Clients", "Clients"), callback_data="menu_clients")],
        [InlineKeyboardButton(text=_txt("Inbounds", "Inbounds"), callback_data="menu_inbounds")],
        [InlineKeyboardButton(text=_txt("Routing", "Routing"), callback_data="menu_routing")],
        [InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="main_menu")],
    )


def kb_clients_list(clients: list, page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * page_size
    end = start + page_size
    page_clients = clients[start:end]

    for c in page_clients:
        icon = "🟢" if c.get("enable") else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{icon} {c['name']} [{c.get('protocol', '?')}]",
                callback_data=f"client_detail_{c['id']}",
            )
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"clients_page_{page - 1}"))
    if end < len(clients):
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"clients_page_{page + 1}"))
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text=_txt("Add", "Add"), callback_data="client_add"),
        InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_server"),
    )
    return builder.as_markup()


def kb_client_detail(client_id: int) -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=_txt("Enable/Disable", "Enable/Disable"), callback_data=f"client_toggle_{client_id}"),
            InlineKeyboardButton(text=_txt("Reset Stats", "Reset Stats"), callback_data=f"client_reset_stats_{client_id}"),
        ],
        [
            InlineKeyboardButton(text=_txt("Subscription URL", "Subscription URL"), callback_data=f"client_suburl_{client_id}"),
            InlineKeyboardButton(text=_txt("Config File", "Config File"), callback_data=f"client_sub_{client_id}"),
        ],
        [
            InlineKeyboardButton(text=_txt("Template", "Template"), callback_data=f"client_tmpl_{client_id}"),
            InlineKeyboardButton(text=_txt("Delete", "Delete"), callback_data=f"client_delete_{client_id}"),
        ],
        [InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_clients")],
    )


def kb_inbound_select(inbounds: list, prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ib in inbounds:
        tag = ib.get("tag", "?")
        proto = ib.get("type", "?")
        port = ib.get("listen_port", "?")
        builder.row(
            InlineKeyboardButton(
                text=f"[{proto}] {tag} :{port}",
                callback_data=f"{prefix}_inbound_{tag}",
            )
        )
    builder.row(InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data="menu_clients"))
    return builder.as_markup()


def kb_inbounds_list(inbounds: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ib in inbounds:
        tag = ib.get("tag", "?")
        proto = ib.get("type", "?")
        port = ib.get("listen_port", "?")
        builder.row(
            InlineKeyboardButton(
                text=f"[{proto}:{port}] {tag}",
                callback_data=f"inbound_detail_{tag}",
            )
        )
    builder.row(
        InlineKeyboardButton(text=_txt("Add", "Add"), callback_data="inbound_add"),
        InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_server"),
    )
    return builder.as_markup()


def kb_inbound_detail(tag: str) -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=_txt("Delete", "Delete"), callback_data=f"inbound_delete_{tag}"),
            InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_inbounds"),
        ],
    )


def kb_protocol_select(protocols: list, prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for proto in protocols:
        builder.row(
            InlineKeyboardButton(
                text=proto.replace("_", " ").title(),
                callback_data=f"{prefix}_proto_{proto}",
            )
        )
    builder.row(InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data="menu_inbounds"))
    return builder.as_markup()


def kb_routing_menu() -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=_txt("Domains", "Domains"), callback_data="routing_view_domain"),
            InlineKeyboardButton(text=_txt("Domain Suffixes", "Domain Suffixes"), callback_data="routing_view_domain_suffix"),
        ],
        [
            InlineKeyboardButton(text=_txt("Domain Keywords", "Domain Keywords"), callback_data="routing_view_domain_keyword"),
            InlineKeyboardButton(text=_txt("IP CIDR", "IP CIDR"), callback_data="routing_view_ip_cidr"),
        ],
        [InlineKeyboardButton(text=_txt("SRS Rule Sets", "SRS Rule Sets"), callback_data="routing_view_rule_set")],
        [
            InlineKeyboardButton(text=_txt("Add Rule", "Add Rule"), callback_data="routing_add"),
            InlineKeyboardButton(text=_txt("Export", "Export"), callback_data="routing_export"),
        ],
        [
            InlineKeyboardButton(text=_txt("Import", "Import"), callback_data="routing_import"),
            InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_server"),
        ],
    )


def kb_routing_rules_list(rules: list, rule_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in rules[:20]:
        val = r.get("value", "?")
        out = r.get("outbound", "?")
        builder.row(
            InlineKeyboardButton(
                text=f"{val} -> {out}",
                callback_data=f"routing_del_{rule_key}_{val[:30]}",
            )
        )
    builder.row(InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_routing"))
    return builder.as_markup()


def kb_rule_key_select(keys: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in keys.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"rulekey_{key}"))
    builder.row(InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data="menu_routing"))
    return builder.as_markup()


_TEMPLATE_LABELS = {
    "tun": {"ru": "TUN - Телефон / ПК (Android, iOS, Linux, macOS)", "en": "TUN - Phone / PC (Android, iOS, Linux, macOS)"},
    "tun_fakeip": {"ru": "TUN + FakeIP - Телефон / ПК (расширенный DNS)", "en": "TUN + FakeIP - Phone / PC (advanced DNS)"},
    "windows": {"ru": "Windows Service (WinTun + system proxy)", "en": "Windows Service (WinTun + system proxy)"},
    "tproxy": {"ru": "TProxy - Роутер (OpenWRT/Linux)", "en": "TProxy - Router (OpenWRT/Linux)"},
    "socks": {"ru": "SOCKS5 + HTTP - Ручной прокси", "en": "SOCKS5 + HTTP - Manual proxy"},
}

_SRS_INTERVALS = ["1h", "6h", "12h", "1d", "3d", "7d"]
_SRS_DETOURS = [
    ("direct", {"ru": "Direct (GitHub доступен)", "en": "Direct (GitHub reachable)"}),
    ("proxy", {"ru": "Proxy (если GitHub заблокирован)", "en": "Proxy (if GitHub blocked)"}),
]


def kb_template_select(client_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tid, label in _TEMPLATE_LABELS.items():
        builder.button(text=label["ru"] if _is_ru() else label["en"], callback_data=f"sub_tmpl_{client_id}_{tid}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data=f"client_detail_{client_id}"))
    return builder.as_markup()


def kb_srs_interval() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for iv in _SRS_INTERVALS:
        builder.button(text=iv, callback_data=f"srsiv_{iv}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data="menu_routing"))
    return builder.as_markup()


def kb_srs_detour() -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=labels["ru"] if _is_ru() else labels["en"], callback_data=f"srsdt_{key}")
            for key, labels in _SRS_DETOURS
        ],
        [InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data="menu_routing")],
    )


def kb_outbound_select(outbounds: list[str] | None = None) -> InlineKeyboardMarkup:
    if not outbounds:
        outbounds = ["proxy", "direct", "block", "warp", "dns"]
    builder = InlineKeyboardBuilder()
    for ob in outbounds:
        builder.button(text=ob, callback_data=f"outbound_{ob}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data="menu_routing"))
    return builder.as_markup()


def kb_adguard_menu() -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=_txt("Statistics", "Statistics"), callback_data="adguard_stats"),
            InlineKeyboardButton(text=_txt("DNS", "DNS"), callback_data="adguard_dns"),
        ],
        [
            InlineKeyboardButton(text=_txt("Enable", "Enable"), callback_data="adguard_protection_on"),
            InlineKeyboardButton(text=_txt("Disable", "Disable"), callback_data="adguard_protection_off"),
        ],
        [
            InlineKeyboardButton(text=_txt("Filter Rules", "Filter Rules"), callback_data="adguard_rules"),
            InlineKeyboardButton(text=_txt("Sync Clients", "Sync Clients"), callback_data="adguard_sync"),
        ],
        [
            InlineKeyboardButton(text=_txt("Change Password", "Change Password"), callback_data="adguard_change_password"),
            InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="main_menu"),
        ],
    )


def kb_adguard_dns() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("Add Upstream", "Add Upstream"), callback_data="adguard_add_upstream")],
        [InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_adguard")],
    )


def kb_adguard_rules() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("Add Rule", "Add Rule"), callback_data="adguard_add_rule")],
        [InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_adguard")],
    )


def kb_nginx_menu(site_enabled: bool = False, has_override: bool = False) -> InlineKeyboardMarkup:
    webui_btn = (
        InlineKeyboardButton(text=_txt("🟢 Web UI", "🟢 Web UI"), callback_data="nginx_site_off")
        if site_enabled
        else InlineKeyboardButton(text=_txt("🔴 Web UI", "🔴 Web UI"), callback_data="nginx_site_on")
    )
    stub_action_btn = (
        InlineKeyboardButton(text=_txt("🔴 Заглушка", "🔴 Stub"), callback_data="nginx_delete_override")
        if has_override
        else InlineKeyboardButton(text=_txt("🟢 Заглушка", "🟢 Stub"), callback_data="nginx_upload_site")
    )
    return _build(
        [
            InlineKeyboardButton(text=_txt("Configure", "Configure"), callback_data="nginx_configure"),
            InlineKeyboardButton(text=_txt("Issue SSL", "Issue SSL"), callback_data="nginx_ssl"),
        ],
        [
            InlineKeyboardButton(text=_txt("Hidden Paths", "Hidden Paths"), callback_data="nginx_paths"),
            InlineKeyboardButton(text=_txt("Access Logs", "Access Logs"), callback_data="nginx_logs"),
        ],
        [stub_action_btn],
        [webui_btn],
        [InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="main_menu")],
    )


def kb_federation_menu(nodes: list | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if nodes:
        for n in nodes:
            icon = "🟢" if n.get("is_active") else "🔴"
            builder.row(
                InlineKeyboardButton(text=f"{icon} {n['name']}", callback_data=f"fed_ping_{n['id']}"),
                InlineKeyboardButton(text=_txt("Delete", "Delete"), callback_data=f"fed_delete_{n['id']}"),
            )
    builder.row(
        InlineKeyboardButton(text=_txt("Add Node", "Add Node"), callback_data="federation_add"),
        InlineKeyboardButton(text=_txt("Ping All", "Ping All"), callback_data="federation_ping_all"),
    )
    builder.row(
        InlineKeyboardButton(text=_txt("Create Bridge", "Create Bridge"), callback_data="federation_bridge"),
        InlineKeyboardButton(text=_txt("Topology", "Topology"), callback_data="federation_topology"),
    )
    builder.row(InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="main_menu"))
    builder.row(InlineKeyboardButton(text=_txt("My Secret", "My Secret"), callback_data="federation_secret"))
    return builder.as_markup()


def kb_bridge_node_select(nodes: list, selected_ids: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for n in nodes:
        if not n.get("is_active"):
            continue
        nid = n["id"]
        idx = selected_ids.index(nid) + 1 if nid in selected_ids else None
        mark = f"[{idx}]" if idx else "[ ]"
        builder.row(
            InlineKeyboardButton(text=f"{mark} {n['name']} ({n['role']})", callback_data=f"bridge_pick_{nid}")
        )
    done_label = _txt("Create Bridge", "Create Bridge") if selected_ids else _txt("Select nodes first", "Select nodes first")
    builder.row(
        InlineKeyboardButton(text=done_label, callback_data="bridge_confirm"),
        InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data="menu_federation"),
    )
    return builder.as_markup()


def kb_nodes_list(nodes: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for n in nodes:
        icon = "🟢" if n.get("is_active") else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{icon} {n['name']} [{n['role']}]",
                callback_data=f"fed_ping_{n['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="menu_federation"))
    return builder.as_markup()


def kb_node_role() -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=_txt("Node", "Node"), callback_data="noderole_node"),
            InlineKeyboardButton(text=_txt("Bridge", "Bridge"), callback_data="noderole_bridge"),
        ],
        [InlineKeyboardButton(text=_txt("Cancel", "Cancel"), callback_data="menu_federation")],
    )


def kb_admin_menu() -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=_txt("Admins", "Admins"), callback_data="admin_list"),
            InlineKeyboardButton(text=_txt("Add Admin", "Add Admin"), callback_data="admin_add"),
        ],
        [InlineKeyboardButton(text=_txt("Audit Log", "Audit Log"), callback_data="admin_audit_log")],
        [InlineKeyboardButton(text=_txt("Back", "Back"), callback_data="main_menu")],
    )
