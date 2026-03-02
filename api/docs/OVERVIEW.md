# Singbox UI Bot — Обзор системы / System Overview

---

## 🇷🇺 Русский

### Что это такое

**Singbox UI Bot** — это система управления VPN-сервером на базе [Sing-Box](https://github.com/SagerNet/sing-box) с двумя интерфейсами:

- **Telegram-бот** — управление через мессенджер с любого устройства
- **Web UI** — браузерная панель управления на том же сервере

Оба интерфейса работают с **одним бэкендом (FastAPI)** и имеют **полностью одинаковый функционал**. Это не два разных приложения — это два способа работать с одной системой.

---

### Зачем это нужно

| Проблема | Решение |
|----------|---------|
| Нужно управлять VPN-клиентами удалённо | Telegram-бот доступен с любого телефона |
| Telegram может быть заблокирован | Web UI работает напрямую через браузер |
| Сложно настраивать Sing-Box вручную | Бот/UI автоматически пишет config.json |
| Нужен DNS-фильтр для рекламы | Встроенная интеграция с AdGuard Home |
| Один сервер — мало | Федерация позволяет объединить серверы в сеть |
| Сервер выглядит как VPN-сервер | Nginx с заглушкой скрывает назначение |

---

### Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                         Пользователь                            │
└──────────────┬──────────────────────────────────────┬──────────┘
               │ Telegram                              │ Браузер
               ▼                                       ▼
┌──────────────────────┐                ┌──────────────────────────┐
│    bot/ — aiogram    │                │    web/ — Alpine.js SPA  │
│  Тонкий UI-клиент    │                │    Тонкий UI-клиент      │
│  FSM-диалоги         │                │    Таблицы, формы, модалы│
└──────────┬───────────┘                └─────────────┬────────────┘
           │ X-Internal-Token                          │ JWT Bearer
           └───────────────────────┬───────────────────┘
                                   ▼
              ┌────────────────────────────────────────┐
              │           api/ — FastAPI               │
              │      Вся бизнес-логика здесь           │
              │  /api/server  /api/clients             │
              │  /api/inbounds  /api/routing           │
              │  /api/adguard  /api/nginx              │
              │  /api/federation  /api/admin           │
              └───────────┬────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   config/sing-box/   AdGuard Home    Nginx
   config.json        REST API :3000  templates
   (читается/пишется) (HTTP клиент)   (Jinja2)
          │
          ▼
   ┌─────────────┐
   │  Sing-Box   │  ← VPN-ядро (отдельный контейнер)
   │  контейнер  │    читает config.json
   └─────────────┘
```

**Ключевой принцип:** бот и сайт — это просто HTTP-клиенты. Логика живёт только в `api/`. Добавить третий интерфейс (например мобильное приложение) можно без изменения бэкенда.

---

### Компоненты системы

#### 4 Docker-контейнера

| Контейнер | Образ | Порты | Роль |
|-----------|-------|-------|------|
| `singbox_app` | собственный Python 3.11 | `8080` | FastAPI + aiogram в одном процессе |
| `singbox_core` | ghcr.io/sagernet/sing-box | сетевые порты VPN | VPN-ядро, читает config.json |
| `singbox_adguard` | adguard/adguardhome | `53`, `3000` | DNS-сервер с фильтрацией |
| `singbox_nginx` | nginx:alpine | `80`, `443` | Reverse proxy, SSL, публичный сайт |

#### База данных SQLite (`data/app.db`)

| Таблица | Содержимое |
|---------|-----------|
| `clients` | VPN-пользователи: имя, uuid/пароль, лимиты, статистика |
| `inbounds` | Метаданные inbound-конфигураций |
| `web_users` | Учётные записи Web UI |
| `admins` | Telegram-администраторы |
| `audit_log` | Журнал всех действий |
| `federation_nodes` | Список удалённых серверов-нод |
| `app_settings` | Настройки приложения |

#### Основные файлы конфигурации

| Файл | Что хранит |
|------|-----------|
| `.env` | Все секреты: токены, пароли, домен |
| `config/sing-box/config.json` | Живой конфиг Sing-Box (inbounds, routing, DNS) |
| `nginx/conf.d/singbox.conf` | Конфиг Nginx (генерируется автоматически) |
| `nginx/override/index.html` | Кастомный публичный сайт (опционально) |
| `nginx/htpasswd/.htpasswd` | htpasswd для 401-заглушки (случайный пароль) |

---

### Поток данных: пример добавления клиента

```
1. Admin → Telegram: нажимает "➕ Add Client"
2. Bot (aiogram FSM): собирает: имя, inbound, лимит, срок
3. Bot → POST /api/clients/ { name, inbound_tag, ... }
   (Header: X-Internal-Token)
4. API (clients router):
   а) Находит inbound в config.json
   б) Определяет протокол → генерирует uuid или пароль
   с) SingBoxService.add_user_to_inbound() → пишет в config.json
   д) SingBoxService.reload() → docker exec → sing-box reload
   е) Сохраняет метаданные в SQLite (Client таблица)
   ж) Пишет AuditLog запись
5. API → Bot: { id, name, sub_id, ... }
6. Bot → Admin: "✅ Клиент John создан. Sub ID: abc123"
```

---

### Безопасность

| Механизм | Где применяется |
|----------|----------------|
| **JWT Bearer** | Web UI → API (токен 7 дней, HS256) |
| **X-Internal-Token** | Бот → API (shared secret из .env) |
| **HMAC-SHA256** | Федерация (inter-server auth, replay protection 60s) |
| **bcrypt** | Хэш пароля Web UI в БД |
| **Admin whitelist** | Telegram: проверка user_id в env + таблице admins |
| **Rate limiting** | 30 запросов / 60 секунд на пользователя |
| **Audit log** | Все изменения логируются с actor + timestamp |
| **Скрытые пути** | URL панели = SHA256(SECRET_KEY) — невозможно угадать |
| **401 заглушка** | Корень сайта выглядит как защищённый ресурс |

---

### Функционал по разделам

#### 🖥 Сервер
- Статус Sing-Box (запущен/остановлен)
- Логи контейнера в реальном времени
- Перезагрузка конфига (graceful, без разрыва соединений)
- Полный рестарт контейнера
- Просмотр raw config.json
- Генерация Reality keypair

#### 🔌 Inbounds (входящие соединения)
- Добавление: VLESS Reality, VLESS WS, VMess WS, Trojan, Shadowsocks, Hysteria2, TUIC
- Для Reality — ключи генерируются автоматически (`sing-box generate reality-keypair`)
- Удаление inbound (вместе с пользователями)
- Просмотр конфигурации

#### 👥 Clients (пользователи VPN)
- Создание с выбором протокола, лимита трафика, срока действия
- Просмотр статистики (upload/download)
- Скачать client-side config.json для импорта в Sing-Box app
- QR-код для сканирования
- Включить/отключить без удаления
- Сбросить статистику трафика
- Удаление

#### 🗺 Routing (маршрутизация)
- Правила: domain, domain_suffix, domain_keyword, ip_cidr, geosite, geoip, rule_set
- Действия: proxy, direct, block, dns
- Импорт/экспорт правил в JSON
- Добавление внешних rule set по URL (автоскачиваются Sing-Box)

#### 🛡 AdGuard Home
- Включение/выключение DNS-защиты
- Статистика запросов за 24 часа
- Управление upstream DNS
- Добавление/удаление фильтр-правил
- Синхронизация клиентов из Sing-Box → AdGuard

#### 🌐 Nginx
- Генерация конфига из шаблона (Jinja2) + перезагрузка
- Выпуск SSL сертификата через certbot
- Загрузка кастомного сайта (HTML или ZIP-архив)
- Удаление кастомного сайта (возврат к 401-заглушке)
- Просмотр access логов
- Просмотр скрытых путей к панелям

#### 🔗 Federation
- Добавление удалённых серверов-нод
- Ping всех нод
- Создание bridge-цепочки (multi-hop VPN)
- Просмотр топологии сети

#### 👑 Admin
- Управление Telegram-администраторами
- Журнал аудита (кто что сделал и когда)
- Смена пароля Web UI

#### ⚙️ Settings
- Смена часового пояса (выбор из списка, без ввода вручную)
- Смена языка бота (ru / en)
- Статус автоперезапуска Docker и автообновления SSL

#### 🔧 Maintenance (Обслуживание)
- **Backup:** скачать/отправить ZIP (config.json + app.db), автобэкап по расписанию
- **Logs:** скачать, очистить отдельный или все логи Nginx, авто-очистка по расписанию
- **IP Ban:** ручная блокировка IP, автоанализ логов на подозрительные IP, массовый бан

#### 📚 Docs (Документация)
- Полная документация доступна прямо внутри бота и Web UI
- Документы: Обзор, Установка, API Reference, Федерация, Web UI, Обслуживание

---

## 🇬🇧 English

### What is this

**Singbox UI Bot** is a management system for a [Sing-Box](https://github.com/SagerNet/sing-box) VPN server with two interfaces:

- **Telegram Bot** — manage via messenger from any device
- **Web UI** — browser-based admin panel on the same server

Both interfaces share **one backend (FastAPI)** and have **exactly the same functionality**. This is not two separate applications — it is two ways to interact with one system.

---

### Why you need this

| Problem | Solution |
|---------|----------|
| Need to manage VPN clients remotely | Telegram bot works from any phone |
| Telegram might be blocked | Web UI works directly in a browser |
| Manually editing Sing-Box config is hard | Bot/UI writes config.json automatically |
| Need DNS-based ad blocking | Built-in AdGuard Home integration |
| One server is not enough | Federation lets you link servers into a network |
| Server looks like a VPN server | Nginx with a stub site hides its purpose |

---

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           User/Admin                            │
└──────────────┬──────────────────────────────────────┬──────────┘
               │ Telegram                              │ Browser
               ▼                                       ▼
┌──────────────────────┐                ┌──────────────────────────┐
│   bot/ — aiogram     │                │   web/ — Alpine.js SPA   │
│   Thin UI client     │                │   Thin UI client         │
│   FSM dialogs        │                │   Tables, forms, modals  │
└──────────┬───────────┘                └─────────────┬────────────┘
           │ X-Internal-Token                          │ JWT Bearer
           └───────────────────────┬───────────────────┘
                                   ▼
              ┌────────────────────────────────────────┐
              │           api/ — FastAPI               │
              │       All business logic here          │
              │  /api/server  /api/clients             │
              │  /api/inbounds  /api/routing           │
              │  /api/adguard  /api/nginx              │
              │  /api/federation  /api/admin           │
              └───────────┬────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   config/sing-box/   AdGuard Home    Nginx
   config.json        REST API :3000  templates
   (read/write)       (HTTP client)   (Jinja2)
          │
          ▼
   ┌─────────────┐
   │  Sing-Box   │  ← VPN core (separate container)
   │  container  │    reads config.json
   └─────────────┘
```

**Key principle:** the bot and website are just HTTP clients. Logic lives only in `api/`. Adding a third interface (e.g. a mobile app) requires no backend changes.

---

### System Components

#### 4 Docker Containers

| Container | Image | Ports | Role |
|-----------|-------|-------|------|
| `singbox_app` | Custom Python 3.11 | `8080` | FastAPI + aiogram in one process |
| `singbox_core` | ghcr.io/sagernet/sing-box | VPN ports | VPN core, reads config.json |
| `singbox_adguard` | adguard/adguardhome | `53`, `3000` | DNS server with filtering |
| `singbox_nginx` | nginx:alpine | `80`, `443` | Reverse proxy, SSL, public site |

#### SQLite Database (`data/app.db`)

| Table | Contents |
|-------|---------|
| `clients` | VPN users: name, uuid/password, limits, stats |
| `inbounds` | Inbound config metadata |
| `web_users` | Web UI accounts |
| `admins` | Telegram administrators |
| `audit_log` | Log of all actions |
| `federation_nodes` | List of remote server nodes |
| `app_settings` | Application settings |

#### Key Config Files

| File | Contents |
|------|---------|
| `.env` | All secrets: tokens, passwords, domain |
| `config/sing-box/config.json` | Live Sing-Box config (inbounds, routing, DNS) |
| `nginx/conf.d/singbox.conf` | Nginx config (auto-generated) |
| `nginx/override/index.html` | Custom public site (optional) |
| `nginx/htpasswd/.htpasswd` | htpasswd for 401 stub (random password) |

---

### Security

| Mechanism | Where used |
|-----------|-----------|
| **JWT Bearer** | Web UI → API (7-day token, HS256) |
| **X-Internal-Token** | Bot → API (shared secret from .env) |
| **HMAC-SHA256** | Federation (inter-server auth, 60s replay protection) |
| **bcrypt** | Web UI password hash in DB |
| **Admin whitelist** | Telegram: user_id check in env + admins table |
| **Rate limiting** | 30 requests / 60 seconds per user |
| **Audit log** | All changes logged with actor + timestamp |
| **Hidden paths** | Panel URL = SHA256(SECRET_KEY) — impossible to guess |
| **401 stub** | Site root looks like a password-protected resource |

---

### Feature Reference

#### 🖥 Server
- Sing-Box status (running/stopped)
- Container logs in real time
- Config reload (graceful, no connection drops)
- Full container restart
- View raw config.json
- Generate Reality keypair

#### 🔌 Inbounds
- Add: VLESS Reality, VLESS WS, VMess WS, Trojan, Shadowsocks, Hysteria2, TUIC
- Reality keys auto-generated (`sing-box generate reality-keypair`)
- Delete inbound (removes all its users too)
- View full config

#### 👥 Clients
- Create with protocol, traffic limit, expiry date
- View statistics (upload/download)
- Download client-side config.json for Sing-Box app
- QR code for scanning
- Enable/disable without deleting
- Reset traffic stats
- Delete

#### 🗺 Routing
- Rules: domain, domain_suffix, domain_keyword, ip_cidr, geosite, geoip, rule_set
- Actions: proxy, direct, block, dns
- Import/export rules as JSON
- Add external rule sets by URL (auto-downloaded by Sing-Box)

#### 🛡 AdGuard Home
- Enable/disable DNS protection
- 24-hour query statistics
- Manage upstream DNS servers
- Add/remove filter rules
- Sync Sing-Box clients → AdGuard

#### 🌐 Nginx
- Generate config from Jinja2 template + reload
- Issue SSL certificate via certbot
- Upload custom site (HTML or ZIP archive)
- Remove custom site (revert to 401 stub)
- View access logs
- View hidden panel paths

#### 🔗 Federation
- Add remote server nodes
- Ping all nodes
- Create bridge chain (multi-hop VPN)
- View network topology

#### 👑 Admin
- Manage Telegram administrators
- Audit log (who did what and when)
- Change Web UI password

#### ⚙️ Settings
- Change timezone (select from list, no manual typing)
- Change bot language (ru / en)
- View Docker auto-restart and SSL auto-renewal status

#### 🔧 Maintenance
- **Backup:** download/send ZIP (config.json + app.db), scheduled auto-backup
- **Logs:** download, clear individual or all Nginx logs, scheduled auto-cleanup
- **IP Ban:** manual IP blocking, auto-analyze logs for suspicious IPs, bulk ban

#### 📚 Docs
- Full documentation accessible directly inside the bot and Web UI
- Documents: Overview, Install, API Reference, Federation, Web UI, Maintenance
