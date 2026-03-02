"""Localised text strings for the bot."""
from bot.config import settings


def t(key: str, **kwargs) -> str:
    lang = settings.bot_lang
    text = TEXTS.get(lang, TEXTS["ru"]).get(key, TEXTS["ru"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text


TEXTS = {
    "ru": {
        # Main menu
        "welcome": "👋 Добро пожаловать в <b>Singbox UI Bot</b>\nВыберите раздел:",
        "main_menu": "📋 Главное меню",

        # Server
        "server_menu": "🖥 Управление сервером",
        "server_status": "📊 Статус",
        "server_restart": "🔄 Рестарт Sing-Box",
        "server_logs": "📜 Логи",
        "server_restarting": "⏳ Перезапуск Sing-Box...",
        "server_restarted": "✅ Sing-Box перезапущен",
        "server_status_tpl": (
            "🖥 <b>Статус сервера</b>\n\n"
            "▪ Sing-Box: {status}\n"
            "▪ Аптайм: {uptime}\n"
            "▪ Входящий трафик: {dl}\n"
            "▪ Исходящий трафик: {ul}\n"
            "▪ Онлайн: {online} польз."
        ),

        # Clients
        "clients_menu": "👥 Клиенты",
        "clients_list": "📋 Список клиентов",
        "clients_add": "➕ Добавить клиента",
        "clients_empty": "Клиентов нет.",
        "client_info": (
            "👤 <b>{name}</b>\n"
            "▪ Трафик: ↓{dl} / ↑{ul}\n"
            "▪ Лимит: {limit}\n"
            "▪ Истекает: {expire}\n"
            "▪ Активен: {active}"
        ),
        "client_added": "✅ Клиент <b>{name}</b> добавлен",
        "client_deleted": "🗑 Клиент удалён",
        "client_stats_reset": "🔄 Статистика сброшена",
        "ask_client_name": "Введите имя клиента:",
        "ask_client_limit": "Введите лимит трафика (ГБ, 0 = без лимита):",
        "ask_client_expire": "Введите срок действия в днях (0 = без ограничений):",

        # Inbounds
        "inbounds_menu": "📡 Inbounds",
        "inbounds_list": "📋 Список inbounds",
        "inbounds_add": "➕ Добавить inbound",
        "inbound_enabled": "✅ Inbound включён",
        "inbound_disabled": "⛔ Inbound выключен",
        "inbound_deleted": "🗑 Inbound удалён",
        "ask_inbound_tag": "Введите тег (название) inbound:",
        "ask_inbound_port": "Введите порт:",
        "select_protocol": "Выберите протокол:",

        # Routing
        "routing_menu": "🔀 Маршрутизация",
        "routing_domains": "🌐 Домены",
        "routing_ips": "🔢 IP/CIDR",
        "routing_geosite": "🗺 GeoSite",
        "routing_geoip": "🗺 GeoIP",
        "routing_rulesets": "📦 Rule Sets",
        "routing_action_direct": "➡ Direct",
        "routing_action_proxy": "🔒 Proxy",
        "routing_action_block": "🚫 Block",
        "routing_action_dns": "🔍 DNS",
        "rule_added": "✅ Правило добавлено",
        "rule_deleted": "🗑 Правило удалено",
        "ask_domain": "Введите домен (например: google.com):",
        "ask_ip": "Введите IP или CIDR (например: 8.8.8.8/32):",
        "ask_geosite": "Введите geosite тег (например: gfw):",
        "ask_geoip": "Введите geoip тег (например: cn):",
        "ask_ruleset_url": "Введите URL rule set (.json или .srs):",

        # AdGuard
        "adguard_menu": "🛡 AdGuard Home",
        "adguard_stats": "📊 Статистика",
        "adguard_upstream": "🔗 Upstream DNS",
        "adguard_rules": "📋 Правила фильтрации",
        "adguard_password": "🔑 Сменить пароль",
        "adguard_sync": "🔄 Синхр. клиентов",
        "adguard_status_on": "✅ AdGuard активен",
        "adguard_status_off": "⛔ AdGuard недоступен",
        "ask_upstream": "Введите upstream DNS сервер (например: tls://8.8.8.8):",
        "ask_filter_rule": "Введите правило фильтрации (например: ||ads.example.com^):",
        "ask_new_password": "Введите новый пароль:",

        # Nginx
        "nginx_menu": "🌐 Nginx",
        "nginx_configure": "⚙️ Настроить",
        "nginx_ssl": "🔒 SSL сертификат",
        "nginx_stub": "🎨 Сайт-заглушка",
        "nginx_logs": "📜 Access логи",
        "nginx_configured": "✅ Nginx настроен",
        "nginx_ssl_issued": "✅ SSL сертификат получен",
        "select_stub_theme": "Выберите тему сайта-заглушки:",

        # Federation
        "federation_menu": "🔗 Федерация ботов",
        "federation_nodes": "🖥 Ноды",
        "federation_add_node": "➕ Добавить ноду",
        "federation_bridge": "🌉 Создать bridge",
        "federation_topology": "🗺 Топология",
        "node_added": "✅ Нода <b>{name}</b> добавлена",
        "node_deleted": "🗑 Нода удалена",
        "node_online": "🟢 онлайн",
        "node_offline": "🔴 офлайн",
        "ask_node_name": "Введите название ноды:",
        "ask_node_url": "Введите URL ноды (например: https://node2.example.com):",
        "ask_node_secret": "Введите секрет федерации ноды:",
        "bridge_created": "✅ Bridge создан: {chain}",
        "select_nodes_for_bridge": "Выберите ноды для цепочки (в нужном порядке):",

        # Admin
        "admin_menu": "⚙️ Настройки",
        "admin_list": "👮 Администраторы",
        "admin_add": "➕ Добавить админа",
        "admin_del": "➖ Удалить админа",
        "admin_backup": "💾 Бэкап",
        "admin_restore": "📥 Восстановить",
        "admin_added": "✅ Администратор добавлен",
        "admin_removed": "🗑 Администратор удалён",
        "ask_admin_id": "Введите Telegram ID нового администратора:",
        "backup_sent": "✅ Бэкап отправлен",

        # Common
        "back": "◀️ Назад",
        "cancel": "❌ Отмена",
        "confirm": "✅ Подтвердить",
        "delete": "🗑 Удалить",
        "enable": "✅ Включить",
        "disable": "⛔ Выключить",
        "refresh": "🔄 Обновить",
        "export": "📤 Экспорт",
        "import_btn": "📥 Импорт",
        "qr_code": "📷 QR-код",
        "subscription": "🔗 Подписка",
        "copy_link": "📋 Скопировать ссылку",
        "error": "❌ Ошибка: {msg}",
        "success": "✅ Успешно",
        "page": "Стр. {page}/{total}",
        "prev": "◀️",
        "next": "▶️",
    },

    "en": {
        # Main menu
        "welcome": "👋 Welcome to <b>Singbox UI Bot</b>\nChoose a section:",
        "main_menu": "📋 Main Menu",

        # Server
        "server_menu": "🖥 Server Management",
        "server_status": "📊 Status",
        "server_restart": "🔄 Restart Sing-Box",
        "server_logs": "📜 Logs",
        "server_restarting": "⏳ Restarting Sing-Box...",
        "server_restarted": "✅ Sing-Box restarted",
        "server_status_tpl": (
            "🖥 <b>Server Status</b>\n\n"
            "▪ Sing-Box: {status}\n"
            "▪ Uptime: {uptime}\n"
            "▪ Download: {dl}\n"
            "▪ Upload: {ul}\n"
            "▪ Online: {online} users"
        ),

        # Clients
        "clients_menu": "👥 Clients",
        "clients_list": "📋 Client List",
        "clients_add": "➕ Add Client",
        "clients_empty": "No clients.",
        "client_info": (
            "👤 <b>{name}</b>\n"
            "▪ Traffic: ↓{dl} / ↑{ul}\n"
            "▪ Limit: {limit}\n"
            "▪ Expires: {expire}\n"
            "▪ Active: {active}"
        ),
        "client_added": "✅ Client <b>{name}</b> added",
        "client_deleted": "🗑 Client deleted",
        "client_stats_reset": "🔄 Stats reset",
        "ask_client_name": "Enter client name:",
        "ask_client_limit": "Enter traffic limit (GB, 0 = unlimited):",
        "ask_client_expire": "Enter expiry in days (0 = no limit):",

        # Inbounds
        "inbounds_menu": "📡 Inbounds",
        "inbounds_list": "📋 Inbound List",
        "inbounds_add": "➕ Add Inbound",
        "inbound_enabled": "✅ Inbound enabled",
        "inbound_disabled": "⛔ Inbound disabled",
        "inbound_deleted": "🗑 Inbound deleted",
        "ask_inbound_tag": "Enter inbound tag (name):",
        "ask_inbound_port": "Enter port:",
        "select_protocol": "Select protocol:",

        # Routing
        "routing_menu": "🔀 Routing",
        "routing_domains": "🌐 Domains",
        "routing_ips": "🔢 IP/CIDR",
        "routing_geosite": "🗺 GeoSite",
        "routing_geoip": "🗺 GeoIP",
        "routing_rulesets": "📦 Rule Sets",
        "routing_action_direct": "➡ Direct",
        "routing_action_proxy": "🔒 Proxy",
        "routing_action_block": "🚫 Block",
        "routing_action_dns": "🔍 DNS",
        "rule_added": "✅ Rule added",
        "rule_deleted": "🗑 Rule deleted",
        "ask_domain": "Enter domain (e.g.: google.com):",
        "ask_ip": "Enter IP or CIDR (e.g.: 8.8.8.8/32):",
        "ask_geosite": "Enter geosite tag (e.g.: gfw):",
        "ask_geoip": "Enter geoip tag (e.g.: cn):",
        "ask_ruleset_url": "Enter rule set URL (.json or .srs):",

        # AdGuard
        "adguard_menu": "🛡 AdGuard Home",
        "adguard_stats": "📊 Stats",
        "adguard_upstream": "🔗 Upstream DNS",
        "adguard_rules": "📋 Filter Rules",
        "adguard_password": "🔑 Change Password",
        "adguard_sync": "🔄 Sync Clients",
        "adguard_status_on": "✅ AdGuard active",
        "adguard_status_off": "⛔ AdGuard unavailable",
        "ask_upstream": "Enter upstream DNS (e.g.: tls://8.8.8.8):",
        "ask_filter_rule": "Enter filter rule (e.g.: ||ads.example.com^):",
        "ask_new_password": "Enter new password:",

        # Nginx
        "nginx_menu": "🌐 Nginx",
        "nginx_configure": "⚙️ Configure",
        "nginx_ssl": "🔒 SSL Certificate",
        "nginx_stub": "🎨 Stub Site",
        "nginx_logs": "📜 Access Logs",
        "nginx_configured": "✅ Nginx configured",
        "nginx_ssl_issued": "✅ SSL certificate issued",
        "select_stub_theme": "Select stub site theme:",

        # Federation
        "federation_menu": "🔗 Bot Federation",
        "federation_nodes": "🖥 Nodes",
        "federation_add_node": "➕ Add Node",
        "federation_bridge": "🌉 Create Bridge",
        "federation_topology": "🗺 Topology",
        "node_added": "✅ Node <b>{name}</b> added",
        "node_deleted": "🗑 Node deleted",
        "node_online": "🟢 online",
        "node_offline": "🔴 offline",
        "ask_node_name": "Enter node name:",
        "ask_node_url": "Enter node URL (e.g.: https://node2.example.com):",
        "ask_node_secret": "Enter node federation secret:",
        "bridge_created": "✅ Bridge created: {chain}",
        "select_nodes_for_bridge": "Select nodes for chain (in order):",

        # Admin
        "admin_menu": "⚙️ Settings",
        "admin_list": "👮 Administrators",
        "admin_add": "➕ Add Admin",
        "admin_del": "➖ Remove Admin",
        "admin_backup": "💾 Backup",
        "admin_restore": "📥 Restore",
        "admin_added": "✅ Administrator added",
        "admin_removed": "🗑 Administrator removed",
        "ask_admin_id": "Enter Telegram ID of new administrator:",
        "backup_sent": "✅ Backup sent",

        # Common
        "back": "◀️ Back",
        "cancel": "❌ Cancel",
        "confirm": "✅ Confirm",
        "delete": "🗑 Delete",
        "enable": "✅ Enable",
        "disable": "⛔ Disable",
        "refresh": "🔄 Refresh",
        "export": "📤 Export",
        "import_btn": "📥 Import",
        "qr_code": "📷 QR Code",
        "subscription": "🔗 Subscription",
        "copy_link": "📋 Copy Link",
        "error": "❌ Error: {msg}",
        "success": "✅ Success",
        "page": "Page {page}/{total}",
        "prev": "◀️",
        "next": "▶️",
    },
}
