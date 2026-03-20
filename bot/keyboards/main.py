"""
All bot keyboards. Callback data patterns match bot/handlers/*.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List

from api.routers.settings_router import get_runtime


# ─── Generic helpers ──────────────────────────────────────────────────────────

def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en

def kb_back(callback: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data=callback)
    ]])


def _build(*rows: List[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


# ─── Main menu ────────────────────────────────────────────────────────────────

def kb_main_menu() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("🖥 Сервер", "🖥 Server"),       callback_data="menu_server"),
         InlineKeyboardButton(text=_txt("👥 Клиенты", "👥 Clients"),      callback_data="menu_clients")],
        [InlineKeyboardButton(text=_txt("🔌 Входящие", "🔌 Inbounds"),    callback_data="menu_inbounds"),
         InlineKeyboardButton(text=_txt("🗺 Маршрутизация", "🗺 Routing"), callback_data="menu_routing")],
        [InlineKeyboardButton(text="🛡 AdGuard",      callback_data="menu_adguard"),
         InlineKeyboardButton(text="🌐 Nginx",        callback_data="menu_nginx")],
        [InlineKeyboardButton(text=_txt("🔗 Федерация", "🔗 Federation"), callback_data="menu_federation"),
         InlineKeyboardButton(text=_txt("👑 Админы", "👑 Admin"),          callback_data="menu_admin")],
        [InlineKeyboardButton(text=_txt("📋 Шаблоны", "📋 Templates"),     callback_data="menu_templates"),
         InlineKeyboardButton(text=_txt("⚙️ Настройки", "⚙️ Settings"),   callback_data="menu_settings")],
        [InlineKeyboardButton(text="📚 Docs",         callback_data="menu_docs"),
         InlineKeyboardButton(text=_txt("🔧 Обслуживание", "🔧 Maintenance"), callback_data="menu_maintenance")],
    )


# ─── Server ───────────────────────────────────────────────────────────────────

def kb_server() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("📊 Статус", "📊 Status"), callback_data="server_status"),
         InlineKeyboardButton(text=_txt("📋 Логи", "📋 Logs"),     callback_data="server_logs")],
        [InlineKeyboardButton(text=_txt("🔄 Перечитать", "🔄 Reload"), callback_data="server_reload"),
         InlineKeyboardButton(text=_txt("♻️ Рестарт", "♻️ Restart"),   callback_data="server_restart")],
        [InlineKeyboardButton(text=_txt("🔐 SSH порт", "🔐 SSH port"), callback_data="server_ssh_port")],
        [InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu")],
    )


# ─── Clients ──────────────────────────────────────────────────────────────────

def kb_clients_list(clients: list, page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * page_size
    end = start + page_size
    page_clients = clients[start:end]

    for c in page_clients:
        icon = "✅" if c.get("enable") else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{icon} {c['name']} [{c.get('protocol', '?')}]",
            callback_data=f"client_detail_{c['id']}",
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"clients_page_{page-1}"))
    if end < len(clients):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"clients_page_{page+1}"))
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text=_txt("➕ Добавить", "➕ Add"), callback_data="client_add"),
        InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu"),
    )
    return builder.as_markup()


def kb_client_detail(client_id: int) -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("🔀 Вкл/выкл", "🔀 Toggle"), callback_data=f"client_toggle_{client_id}"),
         InlineKeyboardButton(text=_txt("📊 Сброс статистики", "📊 Reset stats"), callback_data=f"client_reset_stats_{client_id}")],
        [InlineKeyboardButton(text=_txt("🔗 Ссылка подписки", "🔗 Sub URL"), callback_data=f"client_suburl_{client_id}"),
         InlineKeyboardButton(text=_txt("📄 Конфиг", "📄 Config file"), callback_data=f"client_sub_{client_id}")],
        [InlineKeyboardButton(text=_txt("🎨 Шаблон", "🎨 Template"), callback_data=f"client_tmpl_{client_id}"),
         InlineKeyboardButton(text=_txt("🗑 Удалить", "🗑 Delete"), callback_data=f"client_delete_{client_id}")],
        [InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_clients")],
    )


def kb_inbound_select(inbounds: list, prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ib in inbounds:
        tag = ib.get("tag", "?")
        proto = ib.get("type", "?")
        port = ib.get("listen_port", "?")
        builder.row(InlineKeyboardButton(
            text=f"[{proto}] {tag} :{port}",
            callback_data=f"{prefix}_inbound_{tag}",
        ))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data="menu_clients"))
    return builder.as_markup()


# ─── Inbounds ─────────────────────────────────────────────────────────────────

def kb_inbounds_list(inbounds: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ib in inbounds:
        tag = ib.get("tag", "?")
        proto = ib.get("type", "?")
        port = ib.get("listen_port", "?")
        builder.row(InlineKeyboardButton(
            text=f"[{proto}:{port}] {tag}",
            callback_data=f"inbound_detail_{tag}",
        ))
    builder.row(
        InlineKeyboardButton(text=_txt("➕ Добавить", "➕ Add"), callback_data="inbound_add"),
        InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu"),
    )
    return builder.as_markup()


def kb_inbound_detail(tag: str) -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("🗑 Удалить", "🗑 Delete"), callback_data=f"inbound_delete_{tag}"),
         InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_inbounds")],
    )


def kb_protocol_select(protocols: list, prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for proto in protocols:
        builder.row(InlineKeyboardButton(
            text=proto.replace("_", " ").title(),
            callback_data=f"{prefix}_proto_{proto}",
        ))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data="menu_inbounds"))
    return builder.as_markup()


# ─── Routing ──────────────────────────────────────────────────────────────────

def kb_routing_menu() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("🌐 Домены", "🌐 Domains"), callback_data="routing_view_domain"),
         InlineKeyboardButton(text=_txt("🔠 Суффиксы", "🔠 Suffixes"), callback_data="routing_view_domain_suffix")],
        [InlineKeyboardButton(text=_txt("🔍 Ключевые слова", "🔍 Keywords"), callback_data="routing_view_domain_keyword"),
         InlineKeyboardButton(text=_txt("📍 IP CIDR", "📍 IP CIDRs"), callback_data="routing_view_ip_cidr")],
        [InlineKeyboardButton(text="📦 SRS Rule Sets", callback_data="routing_view_rule_set")],
        [InlineKeyboardButton(text=_txt("➕ Добавить правило", "➕ Add rule"), callback_data="routing_add"),
         InlineKeyboardButton(text=_txt("📤 Экспорт", "📤 Export"), callback_data="routing_export")],
        [InlineKeyboardButton(text=_txt("📥 Импорт", "📥 Import"), callback_data="routing_import"),
         InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu")],
    )


def kb_routing_rules_list(rules: list, rule_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in rules[:20]:
        val = r.get("value", "?")
        out = r.get("outbound", "?")
        builder.row(InlineKeyboardButton(
            text=f"{val} → {out}",
            callback_data=f"routing_del_{rule_key}_{val[:30]}",
        ))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_routing"))
    return builder.as_markup()


def kb_rule_key_select(keys: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in keys.items():
        builder.row(InlineKeyboardButton(text=label, callback_data=f"rulekey_{key}"))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data="menu_routing"))
    return builder.as_markup()


_TEMPLATE_LABELS = {
    "tun":        {"ru": "📱 TUN — Телефон / ПК (Android, iOS, Linux, macOS)", "en": "📱 TUN — Phone / PC (Android, iOS, Linux, macOS)"},
    "tun_fakeip": {"ru": "📱 TUN + FakeIP — Телефон / ПК (продвинутый DNS)", "en": "📱 TUN + FakeIP — Phone / PC (advanced DNS)"},
    "windows":    {"ru": "🪟 Служба Windows (WinTun + системный прокси)", "en": "🪟 Windows Service (WinTun + system proxy)"},
    "tproxy":     {"ru": "📡 TProxy — Роутер (OpenWRT/Linux)", "en": "📡 TProxy — Router (OpenWRT/Linux)"},
    "socks":      {"ru": "🔌 SOCKS5 + HTTP — Ручной прокси", "en": "🔌 SOCKS5 + HTTP — Manual proxy"},
}

_SRS_INTERVALS = ["1h", "6h", "12h", "1d", "3d", "7d"]
_SRS_DETOURS   = [
    ("direct", {"ru": "⬇️ Direct (GitHub доступен)", "en": "⬇️ Direct (GitHub reachable)"}),
    ("proxy", {"ru": "🔀 Proxy (если GitHub заблокирован)", "en": "🔀 Proxy (if GitHub blocked)"}),
]


def kb_template_select(client_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tid, label in _TEMPLATE_LABELS.items():
        builder.button(text=label["ru"] if _is_ru() else label["en"], callback_data=f"sub_tmpl_{client_id}_{tid}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data=f"client_detail_{client_id}"))
    return builder.as_markup()


def kb_srs_interval() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for iv in _SRS_INTERVALS:
        builder.button(text=iv, callback_data=f"srsiv_{iv}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data="menu_routing"))
    return builder.as_markup()


def kb_srs_detour() -> InlineKeyboardMarkup:
    return _build(
        [
            InlineKeyboardButton(text=labels["ru"] if _is_ru() else labels["en"], callback_data=f"srsdt_{key}")
            for key, labels in _SRS_DETOURS
        ],
        [InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data="menu_routing")],
    )


_OUTBOUND_ICONS = {
    "proxy":  "🚀",
    "direct": "✅",
    "block":  "🚫",
    "dns":    "🔡",
}


def kb_outbound_select(outbounds: list[str] | None = None) -> InlineKeyboardMarkup:
    """Build outbound selector. Includes built-ins + any federation/custom node outbounds."""
    if not outbounds:
        outbounds = ["proxy", "direct", "block", "dns"]
    builder = InlineKeyboardBuilder()
    for ob in outbounds:
        icon = _OUTBOUND_ICONS.get(ob, "📡")
        builder.button(text=f"{icon} {ob}", callback_data=f"outbound_{ob}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data="menu_routing"))
    return builder.as_markup()


# ─── AdGuard ──────────────────────────────────────────────────────────────────

def kb_adguard_menu() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("📊 Статистика", "📊 Stats"), callback_data="adguard_stats"),
         InlineKeyboardButton(text="🌐 DNS",          callback_data="adguard_dns")],
        [InlineKeyboardButton(text=_txt("🟢 Включить", "🟢 Enable"), callback_data="adguard_protection_on"),
         InlineKeyboardButton(text=_txt("🔴 Выключить", "🔴 Disable"), callback_data="adguard_protection_off")],
        [InlineKeyboardButton(text=_txt("🚫 Правила фильтра", "🚫 Filter rules"), callback_data="adguard_rules"),
         InlineKeyboardButton(text=_txt("🔄 Синхр. клиентов", "🔄 Sync clients"), callback_data="adguard_sync")],
        [InlineKeyboardButton(text=_txt("🔑 Сменить пароль", "🔑 Change pass"), callback_data="adguard_change_password"),
         InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu")],
    )


def kb_adguard_dns() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("➕ Добавить upstream", "➕ Add upstream"), callback_data="adguard_add_upstream")],
        [InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_adguard")],
    )


def kb_adguard_rules() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("➕ Добавить правило", "➕ Add rule"), callback_data="adguard_add_rule")],
        [InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_adguard")],
    )


# ─── Nginx ────────────────────────────────────────────────────────────────────

def kb_nginx_menu(site_enabled: bool = False) -> InlineKeyboardMarkup:
    site_btn = (
        InlineKeyboardButton(
            text=_txt("🟢 Включить заглушку", "🟢 Enable stub"),
            callback_data="nginx_site_on",
        )
        if not site_enabled else
        InlineKeyboardButton(
            text=_txt("🔴 Выключить заглушку", "🔴 Disable stub"),
            callback_data="nginx_site_off",
        )
    )
    return _build(
        [InlineKeyboardButton(text=_txt("⚙️ Настроить", "⚙️ Configure"), callback_data="nginx_configure"),
         InlineKeyboardButton(text=_txt("🔐 Выпустить SSL", "🔐 Issue SSL"), callback_data="nginx_ssl")],
        [InlineKeyboardButton(text=_txt("🔒 Скрытые пути", "🔒 Hidden paths"), callback_data="nginx_paths"),
         InlineKeyboardButton(text=_txt("📋 Логи доступа", "📋 Access logs"), callback_data="nginx_logs")],
        [InlineKeyboardButton(text=_txt("📤 Загрузить заглушку", "📤 Upload stub"), callback_data="nginx_upload_site"),
         InlineKeyboardButton(text=_txt("🗑 Удалить заглушку", "🗑 Delete stub"), callback_data="nginx_delete_override")],
        [site_btn],
        [InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu")],
    )


# ─── Federation ───────────────────────────────────────────────────────────────

def kb_federation_menu(nodes: list = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if nodes:
        for n in nodes:
            icon = "🟢" if n.get("is_active") else "🔴"
            builder.row(
                InlineKeyboardButton(text=f"{icon} {n['name']}", callback_data=f"fed_ping_{n['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"fed_delete_{n['id']}"),
            )
    builder.row(
        InlineKeyboardButton(text=_txt("➕ Добавить ноду", "➕ Add node"), callback_data="federation_add"),
        InlineKeyboardButton(text=_txt("📡 Пинг всех", "📡 Ping all"), callback_data="federation_ping_all"),
    )
    builder.row(
        InlineKeyboardButton(text=_txt("🌉 Создать Bridge", "🌉 Create Bridge"), callback_data="federation_bridge"),
        InlineKeyboardButton(text=_txt("🗺 Топология", "🗺 Topology"), callback_data="federation_topology"),
    )
    builder.row(
        InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu"),
    )
    builder.row(
        InlineKeyboardButton(text=_txt("Мой секрет", "My secret"), callback_data="federation_secret"),
    )
    return builder.as_markup()


def kb_bridge_node_select(nodes: list, selected_ids: list) -> InlineKeyboardMarkup:
    """Keyboard for selecting nodes in bridge chain order."""
    builder = InlineKeyboardBuilder()
    for n in nodes:
        if not n.get("is_active"):
            continue
        nid = n["id"]
        idx = selected_ids.index(nid) + 1 if nid in selected_ids else None
        mark = f"[{idx}]" if idx else "[ ]"
        builder.row(InlineKeyboardButton(
            text=f"{mark} {n['name']} ({n['role']})",
            callback_data=f"bridge_pick_{nid}",
        ))
    done_label = (
        _txt("✅ Создать bridge", "✅ Create bridge")
        if selected_ids
        else _txt("ℹ️ Сначала выберите ноды", "ℹ️ Select nodes first")
    )
    builder.row(
        InlineKeyboardButton(text=done_label, callback_data="bridge_confirm"),
        InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data="menu_federation"),
    )
    return builder.as_markup()


def kb_nodes_list(nodes: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for n in nodes:
        icon = "🟢" if n.get("is_active") else "🔴"
        builder.row(InlineKeyboardButton(
            text=f"{icon} {n['name']} [{n['role']}]",
            callback_data=f"fed_ping_{n['id']}",
        ))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_federation"))
    return builder.as_markup()


def kb_node_role() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("🔗 Нода", "🔗 Node"), callback_data="noderole_node"),
         InlineKeyboardButton(text="🌉 Bridge", callback_data="noderole_bridge")],
        [InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data="menu_federation")],
    )


# ─── Admin ────────────────────────────────────────────────────────────────────

def kb_admin_menu() -> InlineKeyboardMarkup:
    return _build(
        [InlineKeyboardButton(text=_txt("👥 Админы", "👥 Admins"), callback_data="admin_list"),
         InlineKeyboardButton(text=_txt("➕ Добавить админа", "➕ Add admin"), callback_data="admin_add")],
        [InlineKeyboardButton(text=_txt("📋 Аудит лог", "📋 Audit log"), callback_data="admin_audit_log"),
         InlineKeyboardButton(text=_txt("💾 Бэкап", "💾 Backup"), callback_data="admin_backup")],
        [InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu")],
    )
