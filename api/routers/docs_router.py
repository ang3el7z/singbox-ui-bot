"""
Documentation content — embedded directly in code.
No separate .md files needed.

GET /api/docs/          -> list docs (titles localised by ?lang=ru|en)
GET /api/docs/{id}      -> content in ?lang=ru|en (default: ru)
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import PlainTextResponse
from api.deps import require_any_auth

router = APIRouter()

# ─── Embedded documentation ──────────────────────────────────────────────────

_DOCS: dict[str, dict] = {}

_DOCS["overview"] = {
    "title": {"ru": "📖 Обзор системы", "en": "📖 System Overview"},
    "ru": """
# Singbox UI Bot — Обзор системы / System Overview

---



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
| `admins` | Telegram-администраторы (первый — из мастера /start) |
| `audit_log` | Журнал всех действий |
| `federation_nodes` | Список удалённых серверов-нод |
| `app_settings` | Runtime-настройки: domain, tz, bot_lang (единственный источник правды) |

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
- **Смена домена** — вводится текстом, Nginx перегенерируется автоматически (нужно потом выпустить SSL)
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
""",
    "en": """
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
| `admins` | Telegram administrators (first admin registered via /start wizard) |
| `audit_log` | Log of all actions |
| `federation_nodes` | List of remote server nodes |
| `app_settings` | Runtime settings: domain, tz, bot_lang — single source of truth (set via bot wizard or Web UI) |

#### Key Config Files

| File | Contents |
|------|---------|
| `.env` | Secrets only: tokens, passwords (no domain — it lives in `app_settings`) |
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
- **Change domain** — enter text, Nginx regenerates automatically (issue SSL separately after domain change)
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
""",
}

_DOCS["install"] = {
    "title": {"ru": "🚀 Установка", "en": "🚀 Installation"},
    "ru": """
# Установка

---

### Требования к серверу

| Компонент | Минимум | Рекомендуется |
|-----------|---------|--------------|
| ОС | Ubuntu 22.04 / Debian 12 | Ubuntu 24.04 LTS |
| CPU | 1 ядро | 2 ядра |
| RAM | 512 МБ | 1 ГБ |
| Диск | 10 ГБ | 20 ГБ |
| Docker | 24+ | последняя версия |
| Docker Compose | v2+ | последняя версия |
| Домен | необязателен при установке | A-запись → IP сервера (настраивается через бота) |
| Порты открыты | 80, 443, 53 (TCP+UDP) | + порты VPN (443, 8443 и т.д.) |

> **Домен не нужен заранее.** Установка работает без домена — на IP. Домен, timezone и язык настраиваются через мастер первого запуска `/start` в боте.

---

### Быстрая установка (одной командой)

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

Скрипт задаёт **3 вопроса**, всё остальное — в боте.

---

### Что спрашивает установщик

| Шаг | Поле | Где взять |
|-----|------|-----------|
| 1/3 | **Bot Token** | @BotFather → /newbot |
| 2/3 | **Email** | любой email — только для уведомлений Let's Encrypt |
| 3/3 | **SSH порт** | по умолчанию 22 |

Всё остальное (домен, язык, timezone, ID администратора) — в мастере первого `/start`.

---

### Мастер первого запуска в боте

После установки найди бота в Telegram и отправь `/start`. Запустится мастер настройки:

**Шаг 1 — Язык:** 🇷🇺 Русский / 🇬🇧 English

**Шаг 2 — Часовой пояс:** список из ~22 вариантов с кнопками

**Шаг 3 — Домен (на выбор):**
- `🔗 Использовать X-X-X-X.nip.io` — автоматически работает без DNS, IP сервера определяется автоматически
- `✏️ Ввести свой домен` — введи `vpn.example.com` текстом
- `⏭️ Пропустить` — настроить позже через ⚙️ Настройки

**Результат:** ты зарегистрирован как первый администратор, настройки сохранены в БД.

Если выбрал домен — Nginx автоматически перегенерируется. Затем выпусти SSL:
`/menu → 🌐 Nginx → 🔒 Issue SSL`

---

### .env файл — что в нём

`install.sh` генерирует `.env` автоматически. Вручную заполнять нужно только одно поле:

```env
BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # от @BotFather
EMAIL=admin@example.com                                # для certbot

# Остальное генерируется автоматически случайными значениями:
INTERNAL_TOKEN=...    JWT_SECRET=...    SECRET_KEY=...
FEDERATION_SECRET=... WEB_ADMIN_PASSWORD=... ADGUARD_PASSWORD=...
```

> **Домен, язык, timezone — не хранятся в .env.** Они живут только в базе данных (`data/app.db → app_settings`) и меняются через бот или Web UI.

---

### Ручная установка (шаг за шагом)

#### 1. Установить Docker

```bash
apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com | bash
systemctl enable docker && systemctl start docker
docker --version && docker compose version
```

#### 2. Клонировать репозиторий

```bash
git clone https://github.com/ang3el7z/singbox-ui-bot.git /opt/singbox-ui-bot
cd /opt/singbox-ui-bot
```

#### 3. Создать .env файл

```bash
cp .env.example .env
nano .env
```

Минимальный набор полей:

```env
BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EMAIL=admin@example.com

# Сгенерировать: openssl rand -hex 32
INTERNAL_TOKEN=<32+ символов>
JWT_SECRET=<32+ символов>
FEDERATION_SECRET=<32+ символов>
SECRET_KEY=<32+ символов>

WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=<сложный пароль>
ADGUARD_PASSWORD=<сложный пароль>
```

#### 4. Создать директории

```bash
mkdir -p nginx/conf.d nginx/logs nginx/override nginx/htpasswd nginx/certs
mkdir -p config/sing-box/templates data subs
```

#### 5. Запустить контейнеры

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

#### 6. Настроить через бота

Отправь `/start` боту — пройди мастер (язык → timezone → домен). Домен и SSL настраиваются через Nginx-меню после завершения мастера.

---

### Первые шаги после установки

1. `/start` → мастер настройки → стать первым администратором
2. `/menu` → 🔌 **Inbounds** → ➕ **Add** — добавь VLESS Reality на порту 443
3. `/menu` → 👥 **Clients** → ➕ **Add** — создай клиента, скачай `config.json`, импортируй в Sing-Box
4. Web UI: `http://IP_СЕРВЕРА/web/` (до домена) или `https://домен/web/` (после SSL)

---

### Обновление

Через CLI-утилиту (рекомендуется):
```bash
singbox-ui-bot update
```

Вручную:
```bash
cd /opt/singbox-ui-bot
git pull origin main
docker compose up -d --build
```

Обновление не затрагивает `data/app.db` и `config/sing-box/config.json` — данные сохраняются.

---

### Файрвол (UFW)

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp      # SSH
ufw allow 80/tcp      # HTTP (certbot)
ufw allow 443/tcp     # HTTPS
ufw allow 53/tcp      # DNS
ufw allow 53/udp
ufw allow 8443/tcp    # Trojan/Hysteria2 (если используешь)
ufw allow 10443/udp   # Hysteria2 UDP (если используешь)
ufw --force enable
```

---

### Структура файлов

```
/opt/singbox-ui-bot/
├── .env                        ← только секреты (chmod 600)
├── docker-compose.yml
├── api/                        ← FastAPI бэкенд (вся логика)
├── bot/                        ← aiogram (UI-слой)
├── web/                        ← Alpine.js SPA (UI-слой)
├── config/sing-box/config.json ← живой конфиг Sing-Box
├── nginx/
│   ├── conf.d/singbox.conf     ← генерируется автоматически
│   ├── templates/main.conf.j2  ← Jinja2 шаблон
│   ├── override/               ← загруженный пользователем сайт
│   ├── htpasswd/.htpasswd      ← случайный пароль для 401-заглушки
│   └── logs/                   ← access.log, error.log
└── data/app.db                 ← SQLite (клиенты, настройки, логи)
```

---

### Полезные команды

```bash
# Логи контейнеров
docker compose logs -f app       # FastAPI + бот
docker compose logs -f singbox   # VPN ядро
docker compose logs -f nginx     # Nginx
docker compose logs -f adguard   # AdGuard

# CLI-утилита
singbox-ui-bot status     # статус системы
singbox-ui-bot backup     # создать бэкап
singbox-ui-bot logs       # выбор и просмотр логов
singbox-ui-bot restart    # перезапуск контейнеров
singbox-ui-bot update     # обновить
singbox-ui-bot uninstall  # удалить

# Проверить конфиг Sing-Box
docker exec singbox_core sing-box check -c /etc/sing-box/config.json
```

---

### Решение частых проблем

| Симптом | Причина | Решение |
|---------|---------|---------|
| Бот не отвечает | Неверный BOT_TOKEN | Проверь `.env`, перезапусти: `docker compose restart app` |
| Nginx 502 | app-контейнер не запущен | `docker compose ps`, `docker compose logs app` |
| SSL не выпускается | DNS A-запись не настроена | Убедись что домен смотрит на IP; выпусти через бота после проверки |
| Sing-Box не стартует | Ошибка в config.json | `docker exec singbox_core sing-box check -c /etc/sing-box/config.json` |
| AdGuard не работает как DNS | Порт 53 занят systemd-resolved | `systemctl stop systemd-resolved && systemctl disable systemd-resolved` |
| Первый /start не показывает мастер | Уже есть запись в таблице admins | Проверь БД: `docker exec singbox_app sqlite3 data/app.db "SELECT * FROM admins"` |

---
""",
    "en": """
# Installation

---

### Server Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Ubuntu 22.04 / Debian 12 | Ubuntu 24.04 LTS |
| CPU | 1 core | 2 cores |
| RAM | 512 MB | 1 GB |
| Disk | 10 GB | 20 GB |
| Docker | 24+ | latest |
| Docker Compose | v2+ | latest |
| Domain | not required at install time | A-record → server IP (set via bot) |
| Open ports | 80, 443, 53 (TCP+UDP) | + VPN ports (443, 8443 etc.) |

> **No domain required upfront.** Installation works on a bare IP. Domain, timezone and language are configured through the first-run `/start` wizard in the bot.

---

### Quick Install (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

The installer asks **3 questions** — everything else is configured in the bot.

---

### What the installer asks

| Step | Field | Where to get it |
|------|-------|----------------|
| 1/3 | **Bot Token** | @BotFather → /newbot |
| 2/3 | **Email** | any email — only for Let's Encrypt notifications |
| 3/3 | **SSH port** | default is 22 |

Everything else (domain, language, timezone, admin ID) is set in the first `/start` wizard.

---

### First-run wizard in the bot

After installation, find your bot in Telegram and send `/start`. A setup wizard will launch:

**Step 1 — Language:** 🇷🇺 Russian / 🇬🇧 English

**Step 2 — Timezone:** list of ~22 options via buttons

**Step 3 — Domain (choose one):**
- `🔗 Use X-X-X-X.nip.io` — works immediately without DNS, server IP is auto-detected
- `✏️ Enter custom domain` — type `vpn.example.com`
- `⏭️ Skip` — configure later via ⚙️ Settings

**Result:** you are registered as the first administrator, settings saved to DB.

If you chose a domain — Nginx is auto-regenerated. Then issue SSL:
`/menu → 🌐 Nginx → 🔒 Issue SSL`

---

### .env file — what's in it

`install.sh` generates `.env` automatically. Only one field needs to be filled manually:

```env
BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # from @BotFather
EMAIL=admin@example.com                                # for certbot

# Everything else is auto-generated with random values:
INTERNAL_TOKEN=...    JWT_SECRET=...    SECRET_KEY=...
FEDERATION_SECRET=... WEB_ADMIN_PASSWORD=... ADGUARD_PASSWORD=...
```

> **Domain, language, timezone are NOT in .env.** They live only in the database (`data/app.db → app_settings`) and are changed via the bot or Web UI.

---

### Manual Installation (step by step)

#### 1. Install Docker

```bash
apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com | bash
systemctl enable docker && systemctl start docker
```

#### 2. Clone repository

```bash
git clone https://github.com/ang3el7z/singbox-ui-bot.git /opt/singbox-ui-bot
cd /opt/singbox-ui-bot
```

#### 3. Create .env

```bash
cp .env.example .env
nano .env
```

Minimum required fields:

```env
BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EMAIL=admin@example.com

# Generate with: openssl rand -hex 32
INTERNAL_TOKEN=<32+ chars>
JWT_SECRET=<32+ chars>
FEDERATION_SECRET=<32+ chars>
SECRET_KEY=<32+ chars>

WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=<strong password>
ADGUARD_PASSWORD=<strong password>
```

#### 4. Create directories

```bash
mkdir -p nginx/conf.d nginx/logs nginx/override nginx/htpasswd nginx/certs
mkdir -p config/sing-box/templates data subs
```

#### 5. Start containers

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

#### 6. Configure via bot

Send `/start` to your bot — go through the wizard (language → timezone → domain). Domain and SSL are configured via the Nginx menu after completing the wizard.

---

### First steps after installation

1. `/start` → setup wizard → become first administrator
2. `/menu` → 🔌 **Inbounds** → ➕ **Add** — add VLESS Reality on port 443
3. `/menu` → 👥 **Clients** → ➕ **Add** — create a user, download `config.json`, import to Sing-Box
4. Web UI: `http://SERVER_IP/web/` (before domain) or `https://domain/web/` (after SSL)

---

### Updating

Via CLI (recommended):
```bash
singbox-ui-bot update
```

Manually:
```bash
cd /opt/singbox-ui-bot
git pull origin main
docker compose up -d --build
```

Update does not affect `data/app.db` or `config/sing-box/config.json` — your data is preserved.

---

### Firewall (UFW)

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp      # SSH
ufw allow 80/tcp      # HTTP (certbot)
ufw allow 443/tcp     # HTTPS
ufw allow 53/tcp      # DNS
ufw allow 53/udp
ufw allow 8443/tcp    # Trojan/Hysteria2 (if used)
ufw allow 10443/udp   # Hysteria2 UDP (if used)
ufw --force enable
```

---

### Useful commands

```bash
# Container logs
docker compose logs -f app       # FastAPI + bot
docker compose logs -f singbox   # VPN core
docker compose logs -f nginx
docker compose logs -f adguard

# CLI tool
singbox-ui-bot status     # system status
singbox-ui-bot backup     # create backup
singbox-ui-bot logs       # view logs
singbox-ui-bot restart    # restart containers
singbox-ui-bot update     # pull & rebuild
singbox-ui-bot uninstall  # remove everything

# Validate Sing-Box config
docker exec singbox_core sing-box check -c /etc/sing-box/config.json
```

---

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Bot not responding | Wrong BOT_TOKEN | Check `.env`, restart: `docker compose restart app` |
| Nginx 502 | app container not running | `docker compose ps`, `docker compose logs app` |
| SSL not issued | DNS A-record not set | Ensure domain points to server IP; issue via bot after verifying |
| Sing-Box not starting | Invalid config.json | `docker exec singbox_core sing-box check -c /etc/sing-box/config.json` |
| AdGuard DNS not working | Port 53 occupied by systemd-resolved | `systemctl stop systemd-resolved && systemctl disable systemd-resolved` |
| First /start doesn't show wizard | Admin already exists in DB | Check: `docker exec singbox_app sqlite3 data/app.db "SELECT * FROM admins"` |

---
""",
}

_DOCS["api"] = {
    "title": {"ru": "🔌 API Reference", "en": "🔌 API Reference"},
    "ru": """
# REST API Reference / Справочник REST API

---



### Общие сведения

Все API-эндпоинты доступны по пути `/api/`. Бэкенд запускается на порту `8080` и проксируется через Nginx.

**Интерактивная документация Swagger:** `https://твой-домен.com/api/docs`  
**ReDoc:** `https://твой-домен.com/api/redoc`

### Аутентификация

Система поддерживает два метода аутентификации:

#### 1. JWT Bearer (для Web UI)

```http
Authorization: Bearer <jwt_token>
```

Получение токена:
```http
POST /api/auth/login
Content-Type: application/json

{"username": "admin", "password": "yourpassword"}
```

Ответ:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "username": "admin"
}
```

#### 2. X-Internal-Token (для Telegram-бота)

```http
X-Internal-Token: <значение из .env INTERNAL_TOKEN>
```

Используется только ботом — он работает в том же процессе что и API.

---

### Коды ошибок

| Код | Значение |
|-----|---------|
| `200` | Успех |
| `201` | Создано |
| `400` | Неверный запрос (ошибка в данных) |
| `401` | Не аутентифицирован |
| `403` | Нет прав доступа |
| `404` | Ресурс не найден |
| `422` | Ошибка валидации (Pydantic) |
| `500` | Внутренняя ошибка сервера |
| `502` | Внешний сервис недоступен (AdGuard, Nginx) |

---

### 🔐 Auth — Аутентификация

#### `POST /api/auth/login` — Вход

```bash
curl -X POST https://домен/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username": "admin", "password": "yourpassword"}'
```

Ответ `200`:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "username": "admin"
}
```

#### `GET /api/auth/me` — Текущий пользователь

```bash
curl https://домен/api/auth/me \\
  -H "Authorization: Bearer eyJ..."
```

Ответ `200`:
```json
{"username": "admin", "id": 1}
```

#### `POST /api/auth/change-password` — Смена пароля

```bash
curl -X POST https://домен/api/auth/change-password \\
  -H "Authorization: Bearer eyJ..." \\
  -H "Content-Type: application/json" \\
  -d '{"current_password": "old", "new_password": "newpass123"}'
```

Ответ `200`: `{"detail": "Password changed"}`

---

### 🖥 Server — Управление сервером

#### `GET /api/server/status` — Статус Sing-Box

```bash
curl https://домен/api/server/status \\
  -H "Authorization: Bearer eyJ..."
```

Ответ:
```json
{
  "running": true,
  "container": "singbox_core"
}
```

#### `GET /api/server/logs?lines=100` — Логи контейнера

Параметры: `lines` (int, default=100) — количество последних строк

Ответ:
```json
{
  "logs": [
    "2025-01-01 12:00:00 INFO sing-box started",
    "2025-01-01 12:00:01 INFO inbound/vless-main: listening on :443"
  ]
}
```

#### `POST /api/server/reload` — Перезагрузить конфиг (graceful)

Перечитывает `config.json` без разрыва текущих VPN-соединений.

```bash
curl -X POST https://домен/api/server/reload \\
  -H "Authorization: Bearer eyJ..."
```

Ответ: `{"success": true}`

#### `POST /api/server/restart` — Полный рестарт

Перезапускает Docker-контейнер. Все соединения прерываются.

Ответ: `{"success": true}`

#### `GET /api/server/config` — Получить config.json

Возвращает полный текущий конфиг Sing-Box в виде JSON-объекта.

#### `GET /api/server/keypair` — Сгенерировать Reality keypair

Используется при создании VLESS Reality inbound.

Ответ:
```json
{
  "private_key": "aAbBcC...",
  "public_key": "xXyYzZ..."
}
```

---

### 👥 Clients — Управление пользователями

#### `GET /api/clients/` — Список клиентов

```bash
curl https://домен/api/clients/ \\
  -H "Authorization: Bearer eyJ..."
```

Ответ (массив):
```json
[
  {
    "id": 1,
    "name": "John",
    "inbound_tag": "vless-main",
    "protocol": "vless",
    "uuid": "550e8400-e29b-41d4-a716-446655440000",
    "password": null,
    "sub_id": "abc123def456",
    "total_gb": 50.0,
    "expiry_time": 1735689600000,
    "enable": true,
    "upload": 1073741824,
    "download": 5368709120,
    "tg_id": "123456789",
    "created_at": "2025-01-01T12:00:00"
  }
]
```

**Поля:**
- `uuid` — для протоколов VLESS, VMess, TUIC
- `password` — для Trojan, Shadowsocks, Hysteria2
- `sub_id` — уникальный ID подписки (16 символов hex)
- `total_gb` — лимит трафика (0 = безлимит)
- `expiry_time` — время истечения в миллисекундах Unix (null = бессрочно)
- `upload`/`download` — трафик в байтах

#### `POST /api/clients/` — Создать клиента

```bash
curl -X POST https://домен/api/clients/ \\
  -H "Authorization: Bearer eyJ..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "John",
    "inbound_tag": "vless-main",
    "total_gb": 50,
    "expire_days": 30,
    "tg_id": "123456789"
  }'
```

Параметры:
- `name` (string, обязательно) — имя клиента
- `inbound_tag` (string, обязательно) — тег inbound из config.json
- `total_gb` (float, default=0) — лимит трафика в ГБ
- `expire_days` (int, default=0) — срок действия в днях
- `tg_id` (string, опционально) — Telegram ID для связи

Ответ `201`: объект клиента (как в GET)

#### `PATCH /api/clients/{id}` — Обновить клиента

```bash
curl -X PATCH https://домен/api/clients/1 \\
  -H "Authorization: Bearer eyJ..." \\
  -H "Content-Type: application/json" \\
  -d '{"enable": false}'
```

Обновляемые поля: `enable`, `total_gb`, `expire_days`, `tg_id`

#### `DELETE /api/clients/{id}` — Удалить клиента

Удаляет из config.json и из БД, перезагружает Sing-Box.

Ответ: `{"detail": "Deleted"}`

#### `POST /api/clients/{id}/reset-stats` — Сбросить статистику

Обнуляет `upload` и `download` в БД.

Ответ: `{"detail": "Stats reset"}`

#### `GET /api/clients/{id}/subscription` — Получить конфиг подписки

Возвращает готовый `config.json` для клиентского приложения Sing-Box.

```json
{
  "log": {"level": "info"},
  "inbounds": [
    {"tag": "tun-in", "type": "tun", "address": ["172.19.0.1/30"], "auto_route": true}
  ],
  "outbounds": [
    {
      "tag": "proxy",
      "type": "vless",
      "server": "vpn.example.com",
      "server_port": 443,
      "uuid": "550e8400-...",
      "tls": {
        "enabled": true,
        "reality": {"enabled": true, "public_key": "...", "short_id": "..."}
      }
    },
    {"tag": "direct", "type": "direct"},
    {"tag": "block", "type": "block"}
  ],
  "route": {"final": "proxy"}
}
```

---

### 🔌 Inbounds — Входящие соединения

#### `GET /api/inbounds/` — Список inbounds

Возвращает inbounds напрямую из `config.json` (источник правды).

```json
[
  {
    "type": "vless",
    "tag": "vless-main",
    "listen": "0.0.0.0",
    "listen_port": 443,
    "users": [
      {"name": "John", "uuid": "550e8400-..."}
    ],
    "tls": {
      "enabled": true,
      "reality": {
        "enabled": true,
        "private_key": "...",
        "public_key": "...",
        "short_id": ["abcd1234"]
      }
    }
  }
]
```

#### `POST /api/inbounds/` — Создать inbound

```bash
curl -X POST https://домен/api/inbounds/ \\
  -H "Authorization: Bearer eyJ..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "tag": "vless-main",
    "protocol": "vless_reality",
    "listen_port": 443
  }'
```

Параметры:
- `tag` (string, обязательно) — уникальное имя
- `protocol` (string) — один из: `vless_reality`, `vless_ws`, `vmess_ws`, `trojan`, `shadowsocks`, `hysteria2`, `tuic`
- `listen_port` (int) — порт прослушивания
- `custom_config` (object, опционально) — переопределить поля шаблона

Для `vless_reality` — Reality keypair и short_id генерируются автоматически.  
Для `shadowsocks` — пароль генерируется автоматически.

#### `DELETE /api/inbounds/{tag}` — Удалить inbound

Удаляет из config.json, перезагружает Sing-Box.

---

### 🗺 Routing — Маршрутизация

#### `GET /api/routing/` — Полная секция route

Возвращает объект `route` из config.json целиком.

#### `GET /api/routing/rules/{rule_key}` — Правила по типу

`rule_key`: `domain`, `domain_suffix`, `domain_keyword`, `ip_cidr`, `geosite`, `geoip`, `rule_set`

```bash
curl https://домен/api/routing/rules/domain \\
  -H "Authorization: Bearer eyJ..."
```

Ответ:
```json
[
  {"value": "google.com", "outbound": "proxy"},
  {"value": "ya.ru", "outbound": "direct"}
]
```

#### `POST /api/routing/rules` — Добавить правило

```bash
curl -X POST https://домен/api/routing/rules \\
  -H "Authorization: Bearer eyJ..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "rule_key": "geosite",
    "value": "ru",
    "outbound": "direct"
  }'
```

`outbound`: `proxy` | `direct` | `block` | `dns`

Ответ: `{"detail": "Rule added"}`

#### `DELETE /api/routing/rules?rule_key=geosite&value=ru` — Удалить правило

#### `POST /api/routing/rule-sets` — Добавить remote rule set

```bash
curl -X POST https://домен/api/routing/rule-sets \\
  -H "Authorization: Bearer eyJ..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "tag": "geosite-ads",
    "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ads-all.srs",
    "format": "binary"
  }'
```

#### `GET /api/routing/export` — Экспорт правил

Возвращает `{"rules": [...], "rule_set": [...]}` — сохрани как JSON для бэкапа.

#### `POST /api/routing/import` — Импорт правил

Принимает тот же формат, добавляет к существующим правилам (не заменяет).

---

### 🛡 AdGuard — DNS-фильтрация

#### `GET /api/adguard/status` — Статус

```json
{
  "protection_enabled": true,
  "dns_port": 53,
  "version": "0.107.x",
  "available": true
}
```

Поле `available: false` — AdGuard недоступен (контейнер не запущен).

#### `GET /api/adguard/stats` — Статистика за 24 часа

```json
{
  "dns_queries": 15420,
  "blocked_filtering": 341,
  "replaced_safebrowsing": 2,
  "replaced_parental": 0,
  "avg_processing_time": 1.23
}
```

#### `POST /api/adguard/protection?enabled=true` — Включить/выключить защиту

#### `GET /api/adguard/dns` — DNS-конфигурация

Возвращает upstream DNS серверы и настройки.

#### `POST /api/adguard/dns/upstream` — Добавить upstream DNS

```json
{"upstream": "tls://dns.google"}
```

Примеры upstream:
- `8.8.8.8` — Google DNS
- `1.1.1.1` — Cloudflare DNS  
- `tls://dns.google` — DNS-over-TLS Google
- `https://dns.cloudflare.com/dns-query` — DNS-over-HTTPS

#### `DELETE /api/adguard/dns/upstream?upstream=8.8.8.8` — Удалить upstream

#### `GET /api/adguard/rules` — Список фильтр-правил

```json
{"rules": ["||ads.example.com^", "||tracker.com^"]}
```

#### `POST /api/adguard/rules` — Добавить правило

```json
{"rule": "||doubleclick.net^"}
```

Синтаксис правил: [AdGuard DNS синтаксис](https://adguard-dns.io/kb/general/dns-filtering-syntax/)

#### `POST /api/adguard/sync-clients` — Синхронизировать клиентов

Создаёт записи клиентов в AdGuard для всех VPN-пользователей из БД.

---

### 🌐 Nginx — Управление веб-сервером

#### `GET /api/nginx/status` — Статус и пути

```json
{
  "override": {
    "active": false,
    "files": []
  },
  "paths": {
    "web_ui": "https://vpn.example.com/web/",
    "subscriptions": "https://vpn.example.com/a1b2c3d4e5f6/sub/",
    "adguard": "https://vpn.example.com/f6e5d4c3b2a1/adg/",
    "api": "https://vpn.example.com/abcdef123456/api/",
    "api_docs": "https://vpn.example.com/api/docs"
  }
}
```

#### `POST /api/nginx/configure` — Сгенерировать конфиг и перезагрузить

Рендерит `nginx/templates/main.conf.j2`, записывает в `nginx/conf.d/singbox.conf`, перезагружает Nginx.

Ответ: `{"success": true, "message": "OK"}`

#### `POST /api/nginx/ssl` — Выпустить SSL сертификат

Запускает `certbot certonly --nginx` внутри контейнера.  
Требует: домен, сохранённый в `app_settings` (через бота или Web UI → Settings), и `EMAIL` в `.env`. Домен должен смотреть на сервер, порт 80 открыт.

#### `GET /api/nginx/paths` — Скрытые пути панелей

#### `GET /api/nginx/logs?lines=50` — Access-логи Nginx

#### `POST /api/nginx/override/upload` — Загрузить кастомный сайт

```bash
# Загрузить HTML
curl -X POST https://домен/api/nginx/override/upload \\
  -H "Authorization: Bearer eyJ..." \\
  -F "file=@/path/to/index.html"

# Загрузить ZIP
curl -X POST https://домен/api/nginx/override/upload \\
  -H "Authorization: Bearer eyJ..." \\
  -F "file=@/path/to/site.zip"
```

ZIP должен содержать `index.html` в корне архива.  
Максимальный размер: 20 МБ.

После загрузки Nginx автоматически перезагружается.

Ответ:
```json
{"detail": "ZIP extracted", "files": 12, "type": "zip"}
```

#### `DELETE /api/nginx/override` — Удалить кастомный сайт

Возвращает корень к 401-заглушке.

---

### 🔗 Federation — Федерация серверов

#### `GET /api/federation/` — Список нод

```json
[
  {
    "id": 1,
    "name": "node-amsterdam",
    "url": "https://node.example.com",
    "role": "node",
    "is_active": true,
    "last_ping": "2025-01-01T12:00:00",
    "created_at": "2025-01-01T10:00:00"
  }
]
```

#### `POST /api/federation/` — Добавить ноду

```bash
curl -X POST https://домен/api/federation/ \\
  -H "Authorization: Bearer eyJ..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "node-amsterdam",
    "url": "https://node.example.com",
    "secret": "shared_secret_here",
    "role": "node"
  }'
```

`role`: `node` (точка выхода) | `bridge` (промежуточный хоп)

При добавлении нода сразу пингуется. Поле `is_active` отражает результат.

#### `POST /api/federation/{id}/ping` — Пинг ноды

```json
{"online": true, "node": "node-amsterdam"}
```

#### `POST /api/federation/ping-all` — Пинг всех нод

#### `POST /api/federation/bridge` — Создать bridge-цепочку

```bash
curl -X POST https://домен/api/federation/bridge \\
  -H "Authorization: Bearer eyJ..." \\
  -H "Content-Type: application/json" \\
  -d '{"node_ids": [1, 2]}'
```

Создаёт outbound-конфиги для цепочки: `этот сервер → нода 1 → нода 2 → интернет`

#### `GET /api/federation/topology` — Топология сети

```json
{
  "master": "vpn.example.com",
  "nodes": [
    {"id": 1, "name": "node-amsterdam", "role": "node", "is_active": true, "url": "..."}
  ]
}
```

---

### 👑 Admin — Администраторы

#### `GET /api/admin/admins` — Список Telegram-администраторов

#### `POST /api/admin/admins` — Добавить администратора

```json
{"telegram_id": 123456789, "username": "johndoe"}
```

#### `DELETE /api/admin/admins/{telegram_id}` — Удалить администратора

#### `GET /api/admin/audit-log?limit=50` — Журнал аудита

```json
[
  {
    "id": 1,
    "actor": "tg:123456789",
    "action": "create_client",
    "details": "name=John inbound=vless-main",
    "created_at": "2025-01-01T12:00:00"
  }
]
```

`actor` может быть:
- `tg:123456789` — действие из Telegram-бота
- `web:admin` — действие из Web UI

#### `GET /api/admin/backup` — Скачать резервную копию

Возвращает ZIP-файл с `config.json` и `app.db`.

```bash
curl https://домен/api/admin/backup \\
  -H "Authorization: Bearer eyJ..." \\
  -o backup.zip
```

---

### 🏥 Health Check

```bash
curl https://домен/health
```

Ответ: `{"status": "ok", "version": "2.0.0"}`

Не требует аутентификации. Используется для мониторинга.

---
""",
    "en": """
### General Information

All API endpoints are available at `/api/`. The backend runs on port `8080` and is proxied through Nginx.

**Interactive Swagger docs:** `https://your-domain.com/api/docs`  
**ReDoc:** `https://your-domain.com/api/redoc`

### Authentication

#### JWT Bearer (for Web UI)

```http
Authorization: Bearer <jwt_token>
```

Get token:
```bash
curl -X POST https://domain/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username": "admin", "password": "yourpassword"}'
```

#### X-Internal-Token (for bot)

```http
X-Internal-Token: <value from .env INTERNAL_TOKEN>
```

Used only by the bot (same process as API).

---

### Quick Reference Table

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Login, get JWT |
| GET | `/api/auth/me` | Current user info |
| POST | `/api/auth/change-password` | Change Web UI password |
| GET | `/api/server/status` | Sing-Box running status |
| GET | `/api/server/logs` | Container logs |
| POST | `/api/server/reload` | Graceful config reload |
| POST | `/api/server/restart` | Full container restart |
| GET | `/api/server/config` | Raw config.json |
| GET | `/api/server/keypair` | Generate Reality keypair |
| GET | `/api/clients/` | List all clients |
| POST | `/api/clients/` | Create client |
| GET | `/api/clients/{id}` | Get client details |
| PATCH | `/api/clients/{id}` | Update client |
| DELETE | `/api/clients/{id}` | Delete client |
| POST | `/api/clients/{id}/reset-stats` | Reset traffic counters |
| GET | `/api/clients/{id}/subscription` | Get client config.json |
| GET | `/api/inbounds/` | List inbounds (from config.json) |
| POST | `/api/inbounds/` | Create inbound |
| GET | `/api/inbounds/{tag}` | Get inbound |
| DELETE | `/api/inbounds/{tag}` | Delete inbound |
| GET | `/api/routing/` | Full route section |
| GET | `/api/routing/rules/{key}` | Rules by type |
| POST | `/api/routing/rules` | Add rule |
| DELETE | `/api/routing/rules` | Delete rule |
| POST | `/api/routing/rule-sets` | Add rule set |
| DELETE | `/api/routing/rule-sets/{tag}` | Delete rule set |
| GET | `/api/routing/export` | Export rules JSON |
| POST | `/api/routing/import` | Import rules JSON |
| GET | `/api/adguard/status` | AdGuard status |
| GET | `/api/adguard/stats` | 24h statistics |
| POST | `/api/adguard/protection` | Toggle protection |
| GET | `/api/adguard/dns` | DNS config |
| POST | `/api/adguard/dns/upstream` | Add upstream DNS |
| DELETE | `/api/adguard/dns/upstream` | Remove upstream DNS |
| GET | `/api/adguard/rules` | Filter rules |
| POST | `/api/adguard/rules` | Add filter rule |
| DELETE | `/api/adguard/rules` | Remove filter rule |
| POST | `/api/adguard/sync-clients` | Sync clients to AdGuard |
| GET | `/api/nginx/status` | Override status + hidden paths |
| POST | `/api/nginx/configure` | Generate config + reload |
| POST | `/api/nginx/ssl` | Issue SSL certificate |
| GET | `/api/nginx/paths` | Hidden panel paths |
| GET | `/api/nginx/logs` | Nginx access logs |
| POST | `/api/nginx/override/upload` | Upload custom site |
| DELETE | `/api/nginx/override` | Remove custom site |
| GET | `/api/federation/` | List nodes |
| POST | `/api/federation/` | Add node |
| DELETE | `/api/federation/{id}` | Delete node |
| POST | `/api/federation/{id}/ping` | Ping node |
| POST | `/api/federation/ping-all` | Ping all nodes |
| POST | `/api/federation/bridge` | Create bridge chain |
| GET | `/api/federation/topology` | Network topology |
| GET | `/api/admin/admins` | List admins |
| POST | `/api/admin/admins` | Add admin |
| DELETE | `/api/admin/admins/{tg_id}` | Remove admin |
| GET | `/api/admin/audit-log` | Audit log |
| GET | `/api/admin/backup` | Download backup ZIP |
| GET | `/health` | Health check (no auth) |
""",
}

_DOCS["routing"] = {
    "title": {"ru": "🗺 Роутинг и ноды", "en": "🗺 Routing & Nodes"},
    "ru": """
# Роутинг, SRS-списки и маршрутизация через ноды

---

## Как работает роутинг в Sing-Box

Правила хранятся в `config.json` → секция `route.rules`.  
Sing-Box проверяет их **сверху вниз** и применяет первое совпавшее.  
Если ни одно не сработало — трафик идёт через `final` (по умолчанию `proxy`).

### Типы совпадений (rule_key)

| Тип | Пример | Описание |
|-----|--------|----------|
| `domain` | `youtube.com` | Точный домен |
| `domain_suffix` | `.youtube.com` | Домен и все поддомены |
| `domain_keyword` | `youtube` | Любой домен, содержащий слово |
| `ip_cidr` | `8.8.8.8/32` | IP-адрес или подсеть |
| `geosite` | `ru`, `youtube`, `category-ads-all` | Набор сайтов из встроенной базы |
| `geoip` | `ru`, `cn` | IP-диапазоны страны |
| `rule_set` | URL на `.srs` файл | Внешний набор правил (скачивается автоматически) |

### Действия (outbound)

| Действие | Что происходит |
|----------|---------------|
| `proxy` | Через основной VPN outbound |
| `direct` | Напрямую, без VPN |
| `block` | Заблокировать |
| `dns` | Перенаправить в DNS |
| `exit_node-name` | ⭐ Через конкретную ноду федерации |
| `bridge_to_name` | ⭐ Через мост (промежуточный хоп) |

> **⭐ Ноды федерации** появляются в списке outbound автоматически после того, как ты создал bridge-подключение к ноде через меню Federation → Create Bridge.

---

## Сценарии использования

### Сценарий 1: Рунет напрямую, остальное через VPN

```
geosite:ru  → direct   ← российские сайты без VPN
geoip:ru    → direct   ← российские IP без VPN
(default)   → proxy    ← весь остальной трафик через VPN
```

Добавить в боте:
1. `🗺 Routing → ➕ Add rule`
2. Тип: `geosite`, Значение: `ru`, Действие: `direct`
3. Тип: `geoip`, Значение: `ru`, Действие: `direct`

---

### Сценарий 2: YouTube → российская нода, Twitch → европейский мост

**Шаг 1 — Настройка Federation (один раз):**
1. Убедись что на обоих серверах запущен singbox-ui-bot
2. `/menu → 🔗 Federation → ➕ Add Node`
   - Для YouTube-ноды: имя `ru-node`, URL сервера, `FEDERATION_SECRET` ноды, роль `node`
   - Для Twitch-моста: имя `eu-bridge`, URL, secret, роль `bridge`
3. `/menu → 🔗 Federation → 🌉 Create Bridge`
   - Для YouTube: выбери `ru-node` (1 сервер = прямой хоп)
   - Для Twitch: выбери `eu-bridge` (промежуточный) → и добавь exit-ноду

После Create Bridge Sing-Box автоматически получит outbound-теги:
- `exit_ru-node`
- `bridge_to_eu-bridge`

**Шаг 2 — Добавить правила роутинга:**
1. `/menu → 🗺 Routing → ➕ Add rule`
2. YouTube: Тип `geosite`, Значение `youtube`, Действие → выбери `exit_ru-node`
3. Twitch: Тип `domain`, Значение `twitch.tv`, Действие → выбери `bridge_to_eu-bridge`
4. Twitch stream: Тип `domain_suffix`, Значение `.twitch.tv`, то же действие

Итог:
```
geosite:youtube     → exit_ru-node       ← YouTube через Россию
domain:twitch.tv    → bridge_to_eu-bridge ← Twitch через мост в Европе
.twitch.tv          → bridge_to_eu-bridge ← Twitch CDN тоже
(default)           → proxy              ← остальное как обычно
```

---

### Сценарий 3: Блокировка рекламы через rule_set

Готовые SRS-списки для блокировки рекламы (формат `.srs`):

```
https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-category-ads-all.srs
```

Добавить в боте:
1. `🗺 Routing → ➕ Add rule`
2. Тип: `rule_set`
3. Значение: вставь URL выше
4. Действие: `block`

Sing-Box скачает файл и будет автоматически обновлять его.

---

### Сценарий 4: Конкретные сайты через определённую страну

Хочешь чтобы Netflix шёл через американскую ноду:

```
domain:netflix.com         → exit_us-node
domain_suffix:.netflix.com → exit_us-node
domain_suffix:.nflximg.net → exit_us-node
domain_suffix:.nflxvideo.net → exit_us-node
```

Или через geosite (если список есть):
```
geosite:netflix → exit_us-node
```

---

## Полезные SRS-ссылки

| Список | URL |
|--------|-----|
| Реклама и трекеры | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-category-ads-all.srs` |
| YouTube | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-youtube.srs` |
| Google | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-google.srs` |
| Telegram | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-telegram.srs` |
| Netflix | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-netflix.srs` |
| Twitch | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-twitch.srs` |
| Геообходной | `https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@sing/geo/geosite/geolocation-!cn.srs` |

> Список geosite тегов: [sing-geosite](https://github.com/SagerNet/sing-geosite/tree/rule-set)

---

## Добавление SRS в боте (пошагово)

1. `/menu → 🗺 Routing → ➕ Add rule`
2. Выбери тип: **Rule Set URL**
3. Введи URL `.srs` файла
4. Выбери действие: `block` / `direct` / `exit_нода`
5. Sing-Box автоматически скачает файл и начнёт применять правила

---

## Экспорт и импорт

- **Экспорт** (`📤 Export`) — скачивает `routing_rules.json` со всеми правилами и rule_set
- **Импорт** (`📥 Import`) — загружает JSON, **добавляет** к существующим (не заменяет)

Формат экспортного файла:
```json
{
  "rules": [
    {"outbound": "direct", "geosite": ["ru"]},
    {"outbound": "exit_ru-node", "domain": ["youtube.com"]}
  ],
  "rule_set": [
    {
      "tag": "custom_0",
      "type": "remote",
      "format": "binary",
      "url": "https://.../geosite-category-ads-all.srs",
      "download_detour": "direct"
    }
  ]
}
```

---

## Важно знать

- **Порядок важен**: правила проверяются сверху вниз. Более конкретные ставь выше.
- **После добавления** Sing-Box перезагружается автоматически (graceful reload — соединения не рвутся).
- **Ноды в outbound** появляются только после настройки Federation + Create Bridge.
- **`dns`** — используй только для перенаправления DNS-запросов, не для обычного трафика.

---

## SRS: интервал обновления и загрузка

При добавлении SRS-списка через **бот** или **Web UI** выбирается:

### Интервал обновления (`update_interval`)

Как часто Sing-Box будет скачивать свежую версию списка:

| Значение | Описание |
|----------|---------|
| `1h`  | Каждый час (для очень динамичных блокировок) |
| `6h`  | Каждые 6 часов |
| `12h` | Каждые 12 часов |
| `1d`  | Раз в сутки (рекомендуется, **по умолчанию**) |
| `3d`  | Раз в 3 дня |
| `7d`  | Раз в неделю |

> Если не указать — Sing-Box использует `1d` автоматически.  
> Обновление происходит в фоне при старте и далее по расписанию.  
> Кеш хранится в `/etc/sing-box/cache.db`.

### Detour для загрузки (`download_detour`)

Через какой outbound Sing-Box будет скачивать сам файл правил:

| Значение | Когда использовать |
|----------|--------------------|
| `direct` | GitHub / CDN доступны напрямую с сервера (**по умолчанию**) |
| `proxy`  | Если GitHub заблокирован на сервере — скачать через прокси |

---

## Шаблоны конфигурации для клиентов

При скачивании конфига клиента (бот: кнопка "🔗 Sub URL" или "📄 Config file") выбирается шаблон устройства.

| Шаблон | Устройство | Описание |
|--------|-----------|---------|
| `tun` | 📱 Телефон / ПК (Android, iOS, Linux, macOS) | TUN-интерфейс, автоматический захват трафика, DNS hijack |
| `tun_fakeip` | 📱 Телефон / ПК (продвинутый) | То же, но с FakeIP DNS — быстрее резолвинг |
| `windows` | 🪟 Windows Service | WinTun-драйвер + системный HTTP-прокси. Нужны права администратора |
| `tproxy` | 📡 Роутер (OpenWRT / Linux) | TProxy/redirect, без TUN. Порты 7892/7893. Нужна настройка iptables |
| `socks` | 🔌 Ручной прокси | SOCKS5 на 7891 и HTTP на 7890. Прописать в настройках браузера/приложения |

### TUN (стандартный) — `tun`
- Поднимает виртуальный сетевой интерфейс
- `auto_route: true` — весь трафик системы автоматически идёт через него
- `strict_route: true` — предотвращает утечки
- DNS hijack — перехватывает DNS-запросы, отправляет через Sing-Box
- Подходит для Android/iOS (sing-box client app), Linux, macOS

### TUN + FakeIP — `tun_fakeip`
- Всё то же, плюс FakeIP DNS:  
  браузер получает фейковый IP → Sing-Box знает реальный домен → быстрее маршрутизация
- Диапазон: `198.18.0.0/15` (IPv4)
- Лучший выбор для десктопа при быстром интернете

### Windows Service — `windows`
- TUN через **WinTun-драйвер** (нужна установка: [wintun.net](https://www.wintun.net))
- `stack: system` — системный TCP/IP стек Windows
- `strict_route: true` — блокирует DNS-утечки (Windows Multihomed DNS Behavior)
- `platform.http_proxy` — автоматически выставляет системный HTTP-прокси на 127.0.0.1:7890  
  (для приложений, которые не умеют работать через TUN)
- Порт 7890 — mixed (SOCKS5 + HTTP) как fallback
- **Запуск:**  
  ```
  sing-box.exe run -c config.json
  ```
  (от Администратора, или установить как Windows Service)
- **Установка как сервис (PowerShell, от Администратора):**  
  ```powershell
  sc.exe create SingBox binPath= "C:\sing-box\sing-box.exe run -c C:\sing-box\config.json" start= auto
  sc.exe start SingBox
  ```
- **Удаление сервиса:**  
  ```powershell
  sc.exe stop SingBox
  sc.exe delete SingBox
  ```

### TProxy — `tproxy`
- Для Linux-роутеров (OpenWRT, Debian-роутеры)
- Запускается как сервис, iptables перенаправляет трафик на порты 7892/7893
- Пример iptables для OpenWRT — см. документацию sing-box official

### SOCKS5 — `socks`
- Простейший вариант: Sing-Box слушает 127.0.0.1:7891 (SOCKS5) и :7890 (HTTP)
- Нет автоматического перехвата — вручную прописать в браузере / приложении
- Полезен для тестирования или точечного проксирования
""",
    "en": """
# Routing, SRS Rule Sets and Node-based Routing

---

## How Sing-Box routing works

Rules are stored in `config.json` → `route.rules` section.  
Sing-Box checks them **top to bottom** and applies the first match.  
If no rule matches — traffic goes via `final` (default: `proxy`).

### Match types (rule_key)

| Type | Example | Description |
|------|---------|-------------|
| `domain` | `youtube.com` | Exact domain match |
| `domain_suffix` | `.youtube.com` | Domain and all subdomains |
| `domain_keyword` | `youtube` | Any domain containing the word |
| `ip_cidr` | `8.8.8.8/32` | IP address or subnet |
| `geosite` | `ru`, `youtube`, `category-ads-all` | Site groups from built-in database |
| `geoip` | `ru`, `cn` | Country IP ranges |
| `rule_set` | URL to `.srs` file | External rule set (auto-downloaded) |

### Actions (outbound)

| Action | What happens |
|--------|-------------|
| `proxy` | Through the main VPN outbound |
| `direct` | Directly, bypassing VPN |
| `block` | Block the traffic |
| `dns` | Forward to DNS resolver |
| `exit_node-name` | ⭐ Through a specific federation node |
| `bridge_to_name` | ⭐ Through a bridge (intermediate hop) |

> **⭐ Federation nodes** appear in the outbound list automatically after you create a bridge connection to a node via Federation → Create Bridge.

---

## Use cases

### Scenario 1: Russian sites direct, everything else through VPN

```
geosite:ru  → direct   ← Russian sites without VPN
geoip:ru    → direct   ← Russian IP ranges without VPN
(default)   → proxy    ← everything else through VPN
```

Add in bot:
1. `🗺 Routing → ➕ Add rule`
2. Type: `geosite`, Value: `ru`, Action: `direct`
3. Type: `geoip`, Value: `ru`, Action: `direct`

---

### Scenario 2: YouTube → Russian node, Twitch → European bridge

**Step 1 — Set up Federation (once):**
1. Make sure both servers have singbox-ui-bot running
2. `/menu → 🔗 Federation → ➕ Add Node`
   - For YouTube node: name `ru-node`, server URL, node's `FEDERATION_SECRET`, role `node`
   - For Twitch bridge: name `eu-bridge`, URL, secret, role `bridge`
3. `/menu → 🔗 Federation → 🌉 Create Bridge`
   - For YouTube: select `ru-node` (single hop = direct connection)
   - For Twitch: select `eu-bridge` → then add exit node

After Create Bridge, Sing-Box will have outbound tags:
- `exit_ru-node`
- `bridge_to_eu-bridge`

**Step 2 — Add routing rules:**
1. `/menu → 🗺 Routing → ➕ Add rule`
2. YouTube: Type `geosite`, Value `youtube`, Action → select `exit_ru-node`
3. Twitch: Type `domain`, Value `twitch.tv`, Action → select `bridge_to_eu-bridge`
4. Twitch CDN: Type `domain_suffix`, Value `.twitch.tv`, same action

Result:
```
geosite:youtube     → exit_ru-node        ← YouTube through Russia
domain:twitch.tv    → bridge_to_eu-bridge ← Twitch through EU bridge
.twitch.tv          → bridge_to_eu-bridge ← Twitch CDN too
(default)           → proxy               ← everything else as usual
```

---

### Scenario 3: Block ads via rule_set

Ready-made SRS lists for ad blocking:

```
https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-category-ads-all.srs
```

Add in bot:
1. `🗺 Routing → ➕ Add rule`
2. Type: `rule_set`
3. Value: paste the URL above
4. Action: `block`

Sing-Box will download the file and apply rules automatically.

---

### Scenario 4: Specific sites through a specific country

Route Netflix through a US node:

```
domain:netflix.com         → exit_us-node
domain_suffix:.netflix.com → exit_us-node
domain_suffix:.nflximg.net → exit_us-node
```

Or via geosite:
```
geosite:netflix → exit_us-node
```

---

## Useful SRS links

| List | URL |
|------|-----|
| Ads & trackers | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-category-ads-all.srs` |
| YouTube | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-youtube.srs` |
| Google | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-google.srs` |
| Telegram | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-telegram.srs` |
| Netflix | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-netflix.srs` |
| Twitch | `https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-twitch.srs` |

> Full geosite tag list: [sing-geosite](https://github.com/SagerNet/sing-geosite/tree/rule-set)

---

## Adding SRS in bot (step by step)

1. `/menu → 🗺 Routing → ➕ Add rule`
2. Select type: **Rule Set URL**
3. Enter the `.srs` file URL
4. Select action: `block` / `direct` / `exit_node`
5. Sing-Box downloads the file and starts applying rules

---

## Export and Import

- **Export** (`📤 Export`) — downloads `routing_rules.json` with all rules and rule_sets
- **Import** (`📥 Import`) — uploads JSON, **adds** to existing rules (does not replace)

---

## Important notes

- **Order matters**: rules are checked top to bottom. Put more specific rules first.
- **After adding** — Sing-Box reloads automatically (graceful reload — no connection drops).
- **Node outbounds** only appear after setting up Federation + Create Bridge.
- **`dns`** — use only for DNS query forwarding, not for regular traffic.

---

## SRS: update interval and download detour

When adding an SRS rule set (bot or Web UI), you choose:

### Update interval (`update_interval`)

How often Sing-Box re-downloads the rule set:

| Value | Description |
|-------|-------------|
| `1h`  | Every hour (very dynamic blocklists) |
| `6h`  | Every 6 hours |
| `12h` | Every 12 hours |
| `1d`  | Once per day (recommended, **default**) |
| `3d`  | Every 3 days |
| `7d`  | Weekly |

> If not set — Sing-Box defaults to `1d`.  
> Updates happen in background at startup and then on schedule.  
> Cache is stored in `/etc/sing-box/cache.db`.

### Download detour (`download_detour`)

Which outbound Sing-Box uses to download the rule set file itself:

| Value | When to use |
|-------|------------|
| `direct` | GitHub / CDN reachable directly from server (**default**) |
| `proxy`  | GitHub is blocked on the server — download via proxy |

---

## Client config templates

When downloading a client config (bot: "🔗 Sub URL" or "📄 Config file"), choose a device template:

| Template | Device | Description |
|----------|--------|-------------|
| `tun` | 📱 Phone / PC (Android, iOS, Linux, macOS) | TUN interface, auto traffic capture, DNS hijack |
| `tun_fakeip` | 📱 Phone / PC (advanced) | Same but with FakeIP DNS — faster resolution |
| `windows` | 🪟 Windows Service | WinTun driver + system HTTP proxy. Requires Administrator |
| `tproxy` | 📡 Router (OpenWRT / Linux) | TProxy/redirect, no TUN. Ports 7892/7893. Needs iptables |
| `socks` | 🔌 Manual proxy | SOCKS5 on 7891, HTTP on 7890. Configure apps manually |

### TUN (standard) — `tun`
- Creates a virtual network interface
- `auto_route: true` — all system traffic automatically routes through it
- `strict_route: true` — prevents leaks
- DNS hijack — intercepts DNS queries, processes via Sing-Box
- Suitable for Android/iOS (sing-box client app), Linux, macOS

### TUN + FakeIP — `tun_fakeip`
- Same as TUN plus FakeIP DNS:  
  browser gets fake IP → Sing-Box knows real domain → faster routing
- Range: `198.18.0.0/15` (IPv4)
- Best choice for desktop with fast internet

### Windows Service — `windows`
- TUN via **WinTun driver** (install from [wintun.net](https://www.wintun.net))
- `stack: system` — Windows system TCP/IP stack
- `strict_route: true` — blocks DNS leaks (Windows Multihomed DNS Behavior)
- `platform.http_proxy` — automatically sets system HTTP proxy to 127.0.0.1:7890  
  (for apps that cannot use TUN directly)
- Port 7890 — mixed inbound (SOCKS5 + HTTP) as fallback
- **Run** (as Administrator):  
  ```
  sing-box.exe run -c config.json
  ```
- **Install as Windows Service** (PowerShell, as Administrator):  
  ```powershell
  sc.exe create SingBox binPath= "C:\sing-box\sing-box.exe run -c C:\sing-box\config.json" start= auto
  sc.exe start SingBox
  ```
- **Remove service:**  
  ```powershell
  sc.exe stop SingBox
  sc.exe delete SingBox
  ```

### TProxy — `tproxy`
- For Linux routers (OpenWRT, Debian routers)
- Runs as a service, iptables redirects traffic to ports 7892/7893
- See the official sing-box documentation for OpenWRT iptables examples

### SOCKS5 — `socks`
- Simplest option: Sing-Box listens on 127.0.0.1:7891 (SOCKS5) and :7890 (HTTP)
- No automatic traffic capture — configure manually in browser/app settings
- Useful for testing or per-app proxying
""",
}

_DOCS["federation"] = {
    "title": {"ru": "🔗 Федерация", "en": "🔗 Federation"},
    "ru": """
# Federation — Объединение серверов / Server Federation

---



### Что такое федерация

Федерация — это возможность объединить несколько серверов с установленным `singbox-ui-bot` в единую управляемую сеть. Один сервер становится **master** (главным), остальные — **nodes** (узлами).

**Зачем это нужно:**

| Сценарий | Решение |
|----------|---------|
| Один сервер перегружен | Распределить клиентов по нескольким нодам |
| Нужна анонимность (multi-hop) | Цепочка из двух и более нодов = траффик проходит через несколько стран |
| Нода заблокирована | Переключить клиентов на другую через bridge |
| Разные регионы | Разные ноды для разных стран |

---

### Архитектура федерации

```
┌─────────────────────────────────────────────────────┐
│                    MASTER сервер                     │
│  vpn.example.com                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │  api/ FastAPI                               │    │
│  │  ┌────────────────────────────────────────┐ │    │
│  │  │ federation_service.py                  │ │    │
│  │  │ FederationClient                       │ │    │
│  │  │   - ping nodes                         │ │    │
│  │  │   - create bridge configs              │ │    │
│  │  │   - fetch node outbounds               │ │    │
│  │  └────────────────────────────────────────┘ │    │
│  └─────────────────────────────────────────────┘    │
└──────────────────┬──────────────────────────────────┘
                   │ HMAC-SHA256 HTTP запросы
         ┌─────────┼────────────┐
         ▼         ▼            ▼
   ┌───────────┐ ┌───────────┐ ┌───────────┐
   │  NODE 1   │ │  NODE 2   │ │  NODE 3   │
   │ amsterdam │ │ frankfurt │ │  london   │
   │           │ │           │ │           │
   │/federation│ │/federation│ │/federation│
   │  endpoint │ │  endpoint │ │  endpoint │
   └───────────┘ └───────────┘ └───────────┘
```

---

### Безопасность

Все запросы между мастером и нодами защищены с помощью **HMAC-SHA256**:

```
Timestamp: 1735689600                      ← Unix timestamp
Signature: HMAC-SHA256(secret, timestamp)  ← подписанный timestamp
```

Особенности защиты:
- Каждый запрос содержит timestamp в заголовке `X-Federation-Timestamp`
- Каждый запрос содержит подпись в заголовке `X-Federation-Signature`
- Нода проверяет, что timestamp не старше **60 секунд** (защита от replay-атак)
- `FEDERATION_SECRET` должен быть одинаковым на мастере и всех нодах, иначе запросы отклоняются

---

### Настройка мастера

Добавь ноды через бота или Web UI. Перед добавлением убедись:

1. На ноде установлен `singbox-ui-bot`
2. Нода доступна по HTTPS на `https://нода.example.com`
3. На ноде и мастере один и тот же `FEDERATION_SECRET` в `.env`

Проверить, что нода принимает federation запросы:
```bash
curl -X POST https://нода.example.com/federation/ping \\
  -H "X-Federation-Timestamp: $(date +%s)" \\
  -H "X-Federation-Signature: $(echo -n "$(date +%s)" | openssl dgst -sha256 -hmac "твой_federation_secret" | cut -d' ' -f2)"
```

Ответ: `{"status": "ok", "name": "node-amsterdam"}`

---

### Добавление ноды

#### Через Telegram-бот:
1. `/menu` → 🔗 **Federation** → ➕ **Add Node**
2. Ввести имя ноды (например `amsterdam`)
3. Ввести URL ноды: `https://нода.example.com`
4. Ввести роль: `node` (точка выхода) или `bridge` (промежуточный хоп)
5. Ввести `FEDERATION_SECRET` с ноды
6. Бот автоматически пингует ноду и показывает статус

#### Через Web UI:
1. Меню **Federation** → кнопка **Add Node**
2. Заполнить форму: имя, URL, роль, секрет
3. Нажать **Save**

---

### Режимы работы ноды

#### `node` — Точка выхода

Нода используется как конечная точка VPN. Трафик клиента идёт:
```
Клиент → MASTER → NODE (выход в интернет)
```

Когда мастер создаёт конфиг для этого сценария:
1. Запрашивает inbounds у ноды через `/federation/inbounds`
2. Создаёт у себя outbound-конфиг, указывающий на ноду
3. Создаёт у ноды через `/federation/clients` нового VPN-клиента
4. Отдаёт клиенту конфиг, где трафик проксируется через ноду

#### `bridge` — Промежуточный хоп

Нода стоит в середине цепочки. Используется для multi-hop VPN:
```
Клиент → MASTER → BRIDGE 1 → BRIDGE 2 → NODE (выход)
```

---

### Создание bridge-цепочки (multi-hop)

Multi-hop = трафик проходит через несколько серверов в разных странах. Это значительно усложняет деанонимизацию.

#### Через Telegram-бот:
1. `/menu` → 🔗 **Federation** → 🌉 **Create Bridge**
2. Бот показывает список нод
3. Выбрать 1 или несколько нод для цепочки (например нода 1 → нода 2)
4. Бот создаёт конфигурацию multi-hop

#### Через Web UI:
1. **Federation** → **Create Bridge**
2. Выбрать ноды в нужном порядке (drag & drop или checkbox с порядком)
3. **Create**

#### Что происходит технически:

При создании bridge с нодами `[1, 2]`:

```python
# Псевдокод federation_service.py
nodes = [node1, node2]  # node1 = bridge, node2 = exit

# На node2 (exit): создать клиента
client2 = await FederationClient(node2).create_client(name="bridge-xxx")

# Получить конфиг для подключения к node2
node2_outbound = await FederationClient(node2).get_outbound(client2.id)

# На node1 (bridge): установить outbound к node2
await FederationClient(node1).create_bridge_outbound(
    outbound=node2_outbound,
    next_node_url=node2.url
)

# На мастере: создать outbound к node1, который использует node2 как выход
master_outbound = build_outbound_to(node1, through=node2_outbound)

# Записать в config.json мастера
singbox.save_outbound(master_outbound)
singbox.reload()
```

---

### Federation API (внутренние эндпоинты)

Эти эндпоинты используются только для межсерверного взаимодействия. Все защищены HMAC.

#### `POST /federation/ping` — Проверка доступности

```http
POST /federation/ping
X-Federation-Timestamp: 1735689600
X-Federation-Signature: abc123...

Ответ: {"status": "ok", "name": "server-name"}
```

#### `GET /federation/inbounds` — Получить inbounds

Возвращает список inbounds ноды для создания bridge-подключений.

```http
GET /federation/inbounds
X-Federation-Timestamp: 1735689600
X-Federation-Signature: abc123...

Ответ:
[
  {"type": "vless", "tag": "vless-main", "listen_port": 443, ...}
]
```

#### `POST /federation/clients` — Создать клиента на ноде

```http
POST /federation/clients
X-Federation-Timestamp: 1735689600
X-Federation-Signature: abc123...
Content-Type: application/json

{"name": "bridge-auto-abc123", "inbound_tag": "vless-main"}

Ответ:
{"id": 5, "name": "bridge-auto-abc123", "uuid": "550e8400-..."}
```

#### `GET /federation/clients/{id}/outbound` — Получить outbound-конфиг

Возвращает готовый объект для вставки в чужой config.json.

#### `POST /federation/outbounds` — Установить outbound

```http
POST /federation/outbounds
Content-Type: application/json

{
  "tag": "bridge-next",
  "type": "vless",
  "server": "vpn2.example.com",
  "server_port": 443,
  "uuid": "...",
  "tls": {...}
}
```

---

### Просмотр топологии

Топология показывает схему соединения серверов:

```
Master: vpn.example.com
├── node-amsterdam (node, 🟢 online)  https://amsterdam.example.com
├── node-frankfurt (node, 🟢 online)  https://frankfurt.example.com
└── node-london    (bridge, 🔴 offline) https://london.example.com
```

Через бот: `/menu` → 🔗 **Federation** → 🗺 **Topology**  
Через Web UI: секция **Federation** → вкладка **Topology**

---

### Пример полной настройки multi-hop

#### Условие:
- Мастер: `master.example.com` (основной сервер)
- Нода 1: `amsterdam.example.com` (промежуточный сервер в Нидерландах)  
- Нода 2: `usa.example.com` (выходная нода в США)

#### Шаги:

**1. На всех серверах** установить `singbox-ui-bot` и указать одинаковый `FEDERATION_SECRET`:
```env
FEDERATION_SECRET=одинаковый_секрет_на_всех_серверах
```

**2. На мастере** добавить ноды через бота:
- Имя: `amsterdam`, URL: `https://amsterdam.example.com`, роль: `bridge`
- Имя: `usa`, URL: `https://usa.example.com`, роль: `node`

**3. Пингануть обе ноды:**
`/menu` → 🔗 **Federation** → 📡 **Ping All**

**4. Создать bridge-цепочку:**
`/menu` → 🔗 **Federation** → 🌉 **Create Bridge**  
Выбрать: нода `amsterdam` → нода `usa`

**5. Мастер автоматически:**
- Создаст клиента на `usa.example.com`
- Настроит `amsterdam.example.com` перенаправлять трафик на `usa`
- Настроит мастера слать трафик через `amsterdam`

**6. Клиент подключается к мастеру** — трафик идёт: `Клиент → amsterdam → usa → интернет`

---
""",
    "en": """
### What is Federation

Federation is the ability to connect multiple servers with `singbox-ui-bot` installed into a managed network. One server becomes the **master**, others become **nodes**.

**Why you need it:**

| Scenario | Solution |
|----------|----------|
| One server is overloaded | Distribute clients across nodes |
| Need anonymity (multi-hop) | Chain of 2+ nodes = traffic through multiple countries |
| Node is blocked | Switch clients to another via bridge |
| Different regions | Different nodes for different countries |

---

### Security

All requests between master and nodes are protected with **HMAC-SHA256**:

```
Headers:
  X-Federation-Timestamp: 1735689600
  X-Federation-Signature: HMAC-SHA256(FEDERATION_SECRET, timestamp)
```

Protection features:
- Timestamp is checked to be no older than **60 seconds** (replay protection)
- `FEDERATION_SECRET` must be identical on master and all nodes
- Any request with wrong signature returns `403 Forbidden`

---

### Adding a Node

Prerequisites:
1. `singbox-ui-bot` installed on the node
2. Node accessible at `https://node.example.com`
3. Same `FEDERATION_SECRET` in `.env` on both servers

Via **Telegram bot**:
1. `/menu` → 🔗 **Federation** → ➕ **Add Node**
2. Enter name, URL, role (`node` or `bridge`), secret

Via **Web UI**:
1. **Federation** → **Add Node** button
2. Fill the form and save

---

### Creating a Multi-Hop Bridge

Multi-hop = traffic passes through multiple servers in different countries.

Via **Telegram bot**:
1. `/menu` → 🔗 **Federation** → 🌉 **Create Bridge**
2. Select nodes in order (e.g. node 1 → node 2)

What happens automatically:
1. Master creates a VPN client on the exit node
2. Configures intermediate node(s) to forward to exit
3. Writes outbound config to master's `config.json`
4. Reloads Sing-Box

Result: `Client → master → bridge → exit node → internet`

---

### Viewing Topology

```
Master: vpn.example.com
├── node-amsterdam (node, 🟢 online)
├── node-frankfurt (node, 🟢 online)
└── node-london    (bridge, 🔴 offline)
```

Bot: `/menu` → 🔗 **Federation** → 🗺 **Topology**  
Web UI: **Federation** → **Topology** tab

---

### Example Setup: 2-Hop Chain

1. All servers: same `FEDERATION_SECRET` in `.env`
2. On master: add `amsterdam` (role: `bridge`) and `usa` (role: `node`)
3. Ping all nodes to verify connectivity
4. Create bridge: select `amsterdam` → `usa`
5. Master auto-configures everything
6. Client connects to master → traffic routes: `Client → amsterdam → usa → internet`
""",
}

_DOCS["webui"] = {
    "title": {"ru": "🌐 Web UI", "en": "🌐 Web UI"},
    "ru": """
# Web UI — Веб-интерфейс / Web Interface

---



### Что такое Web UI

Web UI — это браузерный интерфейс управления сервером, альтернатива Telegram-боту. Технически это **Single Page Application (SPA)** на базе [Alpine.js](https://alpinejs.dev/) и [Tailwind CSS](https://tailwindcss.com/).

Ключевые особенности:
- **Без сборки** — чистый HTML/JS/CSS, не требует Node.js, npm или webpack
- **Тот же бэкенд** — Web UI вызывает те же `/api/*` эндпоинты, что и Telegram-бот
- **Полный функционал** — всё, что можно сделать в боте, можно сделать и в браузере
- **Реактивный** — Alpine.js обновляет страницу без перезагрузок

---

### Доступ к Web UI

#### Прямой URL (публичный)
```
https://твой-домен.com/web/
```

#### Скрытый URL (через hidden path)
```
https://твой-домен.com/<hash>/web/
```

Скрытый путь виден в боте: `/menu` → 🌐 **Nginx** → 🔍 **Show Paths**  
Или через API: `GET /api/nginx/paths`

> **Рекомендация:** используй скрытый путь для доступа к панели. Прямой `/web/` может быть обнаружен сканерами.

---

### Вход и аутентификация

1. Открой `https://твой-домен.com/web/`
2. Появится форма входа с полями **Username** и **Password**
3. По умолчанию: `admin` / значение `WEB_ADMIN_PASSWORD` из `.env`
4. После успешного входа — JWT-токен сохраняется в `localStorage`
5. Все дальнейшие запросы к API идут с заголовком `Authorization: Bearer <token>`
6. Сессия действительна **7 дней**
7. При истечении сессии — автоматический редирект на форму входа

**Смена пароля:**  
Меню ☰ → профиль вверху справа → **Change Password**

---

### Структура интерфейса

```
┌────────────────────────────────────────────────────────────┐
│  ☰  Singbox UI Bot         [admin ▼]  [logout]             │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  Sidebar (левое меню):          Основной контент:          │
│  🖥 Server                       ┌──────────────────────┐  │
│  🔌 Inbounds                     │  Карточки, таблицы,  │  │
│  👥 Clients                      │  формы, модальные    │  │
│  🗺 Routing                      │  окна                │  │
│  🛡 AdGuard                      │                      │  │
│  🌐 Nginx                        │                      │  │
│  🔗 Federation                   │                      │  │
│  👑 Admin                        └──────────────────────┘  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

### Раздел: 🖥 Server (Сервер)

**Что отображается:**
- Карточка статуса Sing-Box: `🟢 Running` / `🔴 Stopped`
- Кнопки: **Reload Config** и **Restart**
- Блок с логами контейнера (последние 100 строк, автообновление каждые 5 секунд)
- Кнопка **View Raw Config** — открывает модальное окно с полным `config.json` (с подсветкой)
- Кнопка **Generate Reality Keypair** — генерирует пару ключей для VLESS Reality

**Различие с ботом:** в Web UI логи обновляются автоматически и отображаются в удобном блоке с скроллом. В боте нужно каждый раз нажимать кнопку для обновления.

---

### Раздел: 🔌 Inbounds (Входящие)

**Таблица inbounds содержит столбцы:**
- Тег (`vless-main`)
- Тип протокола (`vless`, `vmess`, `trojan` и т.д.)
- Порт прослушивания
- Количество пользователей
- Кнопки: **View** / **Delete**

**Создание нового inbound** (кнопка **+ Add Inbound**):

Появляется форма с полями:
1. **Tag** — уникальное имя (`vless-main`, `trojan-ws`, и т.д.)
2. **Protocol** — выпадающий список:
   - `VLESS Reality` — рекомендуется (не детектируется)
   - `VLESS WebSocket`
   - `VMess WebSocket`
   - `Trojan`
   - `Shadowsocks`
   - `Hysteria2`
   - `TUIC`
3. **Port** — порт прослушивания
4. **Custom config** (опционально) — JSON для переопределения параметров шаблона

Для **VLESS Reality** Reality-ключи генерируются сервером автоматически при создании.

**Просмотр inbound** (кнопка **View**):

Показывает полный конфиг в `config.json` для этого inbound в модальном окне.

---

### Раздел: 👥 Clients (Клиенты)

**Таблица клиентов:**
| Поле | Описание |
|------|----------|
| Имя | Название клиента |
| Inbound | К какому inbound привязан |
| Протокол | vless, vmess, trojan и т.д. |
| Трафик | ↑ upload / ↓ download / лимит |
| Статус | 🟢 Active / 🔴 Disabled / 🟡 Expired |
| Срок | Дата истечения или ∞ |
| Действия | кнопки |

**Кнопки в строке клиента:**
- **Config** — скачать `client-config.json` для импорта в Sing-Box приложение
- **QR** — показать QR-код для сканирования мобильным приложением
- **Toggle** — включить / отключить без удаления
- **Reset** — сбросить счётчик трафика
- **Delete** — удалить клиента

**Создание клиента** (кнопка **+ Add Client**):

Поля формы:
1. **Name** — имя клиента
2. **Inbound** — выбор из существующих inbounds
3. **Traffic Limit (GB)** — `0` = безлимит
4. **Expire Days** — `0` = бессрочно
5. **Telegram ID** (опционально) — для привязки к Telegram-аккаунту

После создания — клиент появляется в таблице, кнопка **Config** сразу доступна.

**Различие с ботом:** в боте QR выдаётся как фото. В Web UI — показывается в модальном окне прямо на странице. Также в Web UI удобнее работать с большим списком клиентов благодаря табличному представлению.

---

### Раздел: 🗺 Routing (Маршрутизация)

---

#### Как работает роутинг

Правила хранятся напрямую в `config.json` Sing-Box, секция `route.rules`.  
Каждое правило имеет вид: **тип совпадения → outbound (действие)**.

Sing-Box проверяет правила **сверху вниз** и применяет первое совпавшее.  
Если ни одно не совпало — трафик идёт через `final` (по умолчанию `proxy`).

**Типы совпадений:**

| Тип | Пример значения | Когда использовать |
|-----|----------------|-------------------|
| `domain` | `google.com` | Точное совпадение домена |
| `domain_suffix` | `.google.com` | Домен и все поддомены |
| `domain_keyword` | `google` | Содержит ключевое слово |
| `ip_cidr` | `8.8.8.8/32` | IP или подсеть |
| `geosite` | `ru`, `category-ads-all` | Наборы сайтов из geosite базы |
| `geoip` | `cn`, `ru` | IP-адреса страны из geoip базы |
| `rule_set` | URL на `.srs` файл | Внешний набор правил (авто-скачивается) |

**Действия (outbound):**

| Действие | Что происходит |
|----------|---------------|
| `proxy` | Трафик идёт через VPN (зашифровано) |
| `direct` | Трафик идёт напрямую, мимо VPN |
| `block` | Трафик заблокирован |
| `dns` | Перенаправить на DNS-резолвер |

---

#### Практические примеры

**Пример 1: Российские сайты — напрямую, остальное — через VPN**
```
geosite:ru      → direct   (рунет без VPN)
geoip:ru        → direct   (российские IP без VPN)
default (final) → proxy    (весь остальной трафик через VPN)
```

**Пример 2: Заблокировать рекламу**
```
rule_set: https://.../geosite-category-ads-all.srs → block
```

**Пример 3: Конкретный домен через VPN**
```
domain: blocked-site.com  → proxy
```

**Важно:** правила с одинаковым outbound объединяются в один объект `config.json`. Например, добавление `google.com → proxy` и `youtube.com → proxy` создаст одно правило:
```json
{"outbound": "proxy", "domain": ["google.com", "youtube.com"]}
```

---

#### Интерфейс

Переключение по вкладкам (Rule Type selector) — отображает только правила выбранного типа.

**Добавление правила** (кнопка **+ Add Rule**):
1. **Rule Type** — выпадающий список типов
2. **Value** — значение (домен, IP, geosite tag, URL для rule_set)
3. **Outbound** — куда направить трафик

**Rule Sets:**
Внешний `.srs` файл — Sing-Box автоматически скачивает и периодически обновляет его.

**Экспорт/Импорт:**
- **Export** — скачать все правила в JSON
- **Import** — загрузить JSON с правилами (добавятся к существующим, не заменят)

---

### Раздел: 🛡 AdGuard

**Карточки на главной странице раздела:**
- **DNS Queries** — количество запросов за 24 часа
- **Blocked** — заблокировано рекламы/трекеров
- **Protection Status** — включена или выключена
- Кнопка **Toggle Protection** — одним кликом вкл/выкл

**Вкладки:**
1. **DNS Servers** — список upstream DNS, кнопки **Add** и **Delete**
2. **Filter Rules** — блокирующие правила в формате AdGuard DNS syntax
3. **Sync Clients** — синхронизировать клиентов из Sing-Box в AdGuard

**Добавление upstream DNS:**
- `8.8.8.8` — Google
- `1.1.1.1` — Cloudflare
- `tls://dns.google` — Google DNS-over-TLS
- `https://dns.cloudflare.com/dns-query` — Cloudflare DoH

**Фильтр-правила (примеры):**
```
||ads.example.com^      ← заблокировать домен
||*.tracker.com^        ← заблокировать все поддомены
@@||good-site.com^      ← исключение из блокировки
```

---

### Раздел: 🌐 Nginx

**Статус:**
- Показывает, загружен ли кастомный сайт (`override/`)
- Список файлов кастомного сайта (если загружен)

**Скрытые пути** (кнопка **Show Hidden Paths**):

```
Web UI:        https://домен/web/
Subscriptions: https://домен/a1b2c3d4e5f6/sub/
AdGuard:       https://домен/f6e5d4c3b2a1/adg/
API:           https://домен/abcdef123456/api/
API Docs:      https://домен/api/docs
```

Пути генерируются из SHA256 хэша `SECRET_KEY` — невозможно угадать без знания секрета.

**Действия:**
- **Configure & Reload** — регенерировать конфиг из Jinja2 шаблона и перезагрузить Nginx
- **Issue SSL** — выпустить/продлить SSL через certbot (нужны DNS и открытый порт 80)
- **Upload Custom Site** — загрузить HTML файл или ZIP-архив с сайтом-заглушкой
- **Remove Override** — удалить кастомный сайт, вернуться к 401-заглушке
- **View Logs** — показать последние 50 строк Nginx access.log

**Кастомный сайт:**

По умолчанию корень сайта показывает окно авторизации (HTTP 401 Basic Auth) — это маскировка под служебный ресурс.

Чтобы установить свой сайт:
1. Подготовь `index.html` или ZIP-архив (с `index.html` в корне)
2. Нажми **Upload Custom Site**
3. Nginx автоматически перезагрузится

---

### Раздел: 🔗 Federation

---

#### Как работает Federation

Federation позволяет объединить несколько серверов с `singbox-ui-bot`.  
Каждый сервер — нода. Один является **мастером** (откуда управляешь), остальные — **нодами**.

Серверы общаются через `POST /federation/*` эндпоинты, подписанные **HMAC-SHA256** с `FEDERATION_SECRET`.

**Роли нод:**

| Роль | Назначение |
|------|-----------|
| `node` | Точка выхода — пользователи выходят в интернет через этот сервер |
| `bridge` | Промежуточный хоп — трафик проходит через этот сервер и идёт дальше |

---

#### Режим Node (простое подключение)

1. Мастер добавляет ноду: имя, URL, shared secret
2. Мастер получает список inbounds ноды через `/federation/inbounds`
3. В Sing-Box мастера создаётся **outbound** → этот сервер
4. Клиенты мастера могут выходить через эту ноду

---

#### Режим Bridge (multi-hop VPN)

Трафик: `клиент → мастер → нода1 (bridge) → нода2 (exit) → интернет`

При создании bridge с цепочкой `[нода1, нода2]`:
1. Мастер получает inbounds ноды2
2. На ноде1 создаётся outbound к ноде2 (через `/federation/add_outbound`)
3. На мастере создаётся outbound к ноде1
4. Результат: двухступенчатая цепочка через два разных сервера

Используй bridge, когда:
- Нужна анонимность через несколько стран
- Одна нода заблокирована — трафик идёт через другую

---

#### Таблица нод

| Поле | Значение |
|------|---------|
| Имя | `node-amsterdam` |
| URL | `https://amsterdam.example.com` |
| Роль | `node` / `bridge` |
| Статус | 🟢 Online / 🔴 Offline |
| Действия | 📡 Ping / Delete |

**Кнопки:**
- **+ Add Node** — форма: имя, URL, shared secret, роль
- **📡 Ping All** — проверить доступность всех нод
- **📡 Ping** (у каждой ноды) — проверить одну ноду
- **🗺 Topology** — схема сети: мастер + все ноды со статусом

**Топология:**
```
Master: vpn.example.com
├── node-amsterdam [node] 🟢
├── node-frankfurt [node] 🟢
└── node-london    [bridge] 🔴
```

Подробнее о федерации: см. раздел **Federation** в документации (`/menu → 📚 Docs → Federation`).

---

### Раздел: 👑 Admin

**Вкладки:**

1. **Administrators** — список Telegram-администраторов:
   - Telegram ID и имя пользователя
   - Кнопки **Add** / **Delete**
   - Нельзя удалить себя

2. **Audit Log** — журнал всех действий:
   - Кто сделал (`actor`: `tg:123` или `web:admin`)
   - Что сделал (`action`: `create_client`, `delete_inbound`, и т.д.)
   - Подробности (`details`: имена, теги, параметры)
   - Когда (`created_at`)
   - Пагинация (по 50 записей)

3. **Backup** — кнопка **Download Backup**:
   - Скачивает ZIP с `config.json` и `app.db`
   - Имя файла: `singbox-backup-YYYY-MM-DD.zip`

---

### Раздел: ⚙️ Settings

**Domain:**
- Поле ввода домена (например `vpn.example.com`)
- После сохранения Nginx автоматически перегенерируется и перезагружается
- Выпустить SSL нужно отдельно: **Nginx → Issue SSL Certificate**

**Timezone:**
- Выпадающий список с часовыми поясами по группам (Европа, Азия, Америка и т.д.)
- Изменение вступает в силу немедленно (без перезапуска контейнера на Linux)

**Bot Language:**
- Две кнопки: **Russian** / **English**

**System Status:**
- `restart: unless-stopped` — Docker автоматически поднимает контейнер при сбое
- Certbot cron / renewal hook — статус авто-продления SSL

---

### Раздел: 🔧 Maintenance

Три вкладки:

#### 💾 Backup
- **Download ZIP** — скачать бэкап (config.json + app.db) прямо в браузер
- **Send to admins** — отослать ZIP всем Telegram-администраторам немедленно
- **Auto-backup interval** — выпадающий список: Off / 6h / 12h / 24h / 48h / 7 days

#### 📋 Logs
- Список всех файлов `nginx/logs/*.log` с размером
- Для каждого: кнопка `⬇️` скачать, кнопка `🗑` очистить
- **Clear all** — очистить все логи сразу
- **Auto-cleanup interval** — выпадающий список: Off / 24h / 3 days / 7 days / 30 days

#### 🚫 IP Ban
- Форма для ручного добавления IP + причины
- **Scan logs** — анализ `access.log` на подозрительные IP (высокая частота + сканирующие паттерны)
- **Ban all N IPs** — забанить всех найденных разом
- Список текущих банов с типом (`✏️` ручной / `🤖` авто) и кнопкой Unban
- **Clear auto-bans** — удалить только автоматически найденные записи

---

### Сравнение: Telegram-бот vs Web UI

| Функция | Telegram-бот | Web UI |
|---------|-------------|--------|
| Доступность | Любое устройство с Telegram | Любой браузер |
| При блокировке Telegram | ❌ Недоступен | ✅ Работает |
| Уведомления | ✅ Push-уведомления | ❌ Нет (только ручное обновление) |
| Таблицы клиентов | 📋 Пагинация, список кнопок | 📊 Полноценная таблица |
| Логи | Выдаются по кнопке | Автообновление каждые 5 с |
| QR-код | Фото в чате | Модальное окно |
| Мобильный UX | ✅ Нативный (Telegram) | 📱 Адаптивный дизайн |
| Работа с файлами | ✅ Скачать/загрузить через чат | ✅ Скачать/загрузить в браузере |
| Аутентификация | По Telegram ID (admin whitelist) | JWT, username/password |
| Audit log видимость | ❌ Только через команду | ✅ Полная таблица |

**Итог:** оба интерфейса имеют **одинаковый функционал**. Используй тот, который удобнее в конкретной ситуации.

---

### Технические детали Web UI

#### Стек технологий

| Компонент | Технология | Версия |
|-----------|-----------|--------|
| Реактивность | Alpine.js | 3.x (CDN) |
| Стили | Tailwind CSS | 3.x (CDN) |
| HTTP-клиент | Fetch API (нативный) | — |
| Аутентификация | JWT в localStorage | HS256, 7 дней |
| Сборка | ❌ Не требуется | — |

#### Файловая структура

```
web/
├── index.html         ← SPA — одна страница, все компоненты
├── js/
│   ├── api.js         ← fetch-обёртки для /api/* эндпоинтов
│   └── app.js         ← Alpine.js компоненты каждого раздела
└── css/
    └── style.css      ← Tailwind overrides + кастомные стили
```

#### Как работает роутинг

В SPA нет отдельных страниц — смена раздела это изменение переменной `currentSection` в Alpine.js состоянии. Nginx настроен делать `try_files $uri /web/index.html` — т.е. при прямом вводе URL `/web/clients/` вернётся `index.html`, и Alpine.js определит нужный раздел.

#### Безопасность

- JWT хранится в `localStorage` — при компрометации устройства нужно поменять пароль и переиздать токены
- Все запросы идут через HTTPS (Nginx с SSL)
- Нет CORS — всё на одном домене
- CSP заголовки настраиваются в Nginx шаблоне

---
""",
    "en": """
### What is Web UI

Web UI is a browser-based management interface for the server, an alternative to the Telegram bot. Technically it is a **Single Page Application (SPA)** based on [Alpine.js](https://alpinejs.dev/) and [Tailwind CSS](https://tailwindcss.com/).

Key features:
- **No build step** — pure HTML/JS/CSS, no Node.js or npm required
- **Same backend** — Web UI calls the same `/api/*` endpoints as the bot
- **Full functionality** — everything you can do in the bot, you can do in the browser
- **Reactive** — Alpine.js updates the page without full reloads

---

### Accessing Web UI

```
Direct URL:    https://your-domain.com/web/
Hidden URL:    https://your-domain.com/<hash>/web/
```

Hidden path via bot: `/menu` → 🌐 **Nginx** → **Show Paths**  
Or via API: `GET /api/nginx/paths`

---

### Login

1. Go to `https://your-domain.com/web/`
2. Enter username and password
3. Default: `admin` / value of `WEB_ADMIN_PASSWORD` from `.env`
4. JWT stored in `localStorage`, valid for 7 days
5. Session expiry → automatic redirect to login

Change password: ☰ menu → top-right profile → **Change Password**

---

### Sections Overview

| Section | Features |
|---------|----------|
| 🖥 Server | Status, logs (auto-refresh), reload, restart, view config, generate keypair |
| 🔌 Inbounds | Table with all inbounds, add new (with protocol selector), view/delete |
| 👥 Clients | Full table, create, download config, QR code, toggle, reset stats, delete |
| 🗺 Routing | Rules table, add/delete, rule sets, import/export JSON |
| 🛡 AdGuard | Stats cards, toggle protection, manage DNS, filter rules, sync clients |
| 🌐 Nginx | Override status, hidden paths, configure, SSL, upload/remove custom site, logs |
| 🔗 Federation | Nodes table, add node, ping all, create bridge, view topology |
| 👑 Admin | Admins list, audit log, change Web UI password |
| ⚙️ Settings | Domain input (auto-reloads Nginx), timezone dropdown, bot language buttons, system status |
| 🔧 Maintenance | Backup (download/send/schedule), log management, IP ban with log analysis |
| 📚 Docs | Built-in documentation browser with markdown rendering |

---

### Bot vs Web UI Comparison

| Feature | Telegram Bot | Web UI |
|---------|-------------|--------|
| Access device | Any device with Telegram | Any browser |
| If Telegram is blocked | ❌ Unavailable | ✅ Works |
| Push notifications | ✅ Yes | ❌ No |
| Client list display | Paginated list | Full sortable table |
| Server logs | On-demand | Auto-refresh every 5s |
| QR code | Photo in chat | Modal window |
| Authentication | Telegram ID whitelist | JWT username/password |
| Audit log | Command only | Full paginated table |

**Conclusion:** Both interfaces have **identical functionality**. Use whichever is more convenient.

---

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Reactivity | Alpine.js 3.x (CDN) |
| Styles | Tailwind CSS 3.x (CDN) |
| HTTP client | Native Fetch API |
| Auth | JWT in localStorage |
| Build tool | None required |

Files:
```
web/
├── index.html    ← SPA entry point
├── js/api.js     ← API fetch wrappers
├── js/app.js     ← Alpine.js components
└── css/style.css ← Tailwind + custom styles
```
""",
}

_DOCS["maintenance"] = {
    "title": {"ru": "🔧 Обслуживание", "en": "🔧 Maintenance"},
    "ru": """
# Maintenance / Обслуживание

---



### Что это такое

Раздел **Maintenance** (Обслуживание) — это инструмент для автоматического и ручного сопровождения сервера. Доступен как в Telegram-боте (кнопка `🔧 Maintenance`), так и в Web UI (пункт меню `🔧 Maintenance`).

---

### 💾 Резервное копирование (Backup)

#### Что входит в бэкап

| Файл | Содержимое |
|------|-----------|
| `config.json` | Конфигурация Sing-Box (все входящие, маршруты, ключи) |
| `app.db` | База данных SQLite (клиенты, администраторы, настройки, логи аудита) |

#### Ручной бэкап

- **В боте:** кнопка `💾 Backup now` — ZIP-архив отправляется прямо в чат
- **В Web UI:** кнопка `⬇️ Download ZIP` — браузер скачивает архив; кнопка `📤 Send to admins` — архив отсылается всем Telegram-администраторам

#### Автоматический бэкап по расписанию

Настраивается через `⏱ Auto-backup interval`:

| Интервал | Описание |
|---------|----------|
| Off (0) | Автобэкап выключен (по умолчанию) |
| 6 часов | Каждые 6 часов |
| 12 часов | Два раза в день |
| 24 часа | Раз в сутки |
| 48 часов | Каждые двое суток |
| 7 дней | Еженедельно |

При срабатывании планировщик создаёт ZIP и **отправляет его всем Telegram-администраторам** автоматически.

**Как хранится настройка:** в таблице `AppSetting` базы данных, ключ `backup_auto_hours`. При перезапуске контейнера настройка восстанавливается автоматически.

---

### 📋 Управление логами (Logs)

#### Какие логи доступны

Отображаются все файлы с расширением `.log` из папки `nginx/logs/`:

| Файл | Содержимое |
|------|-----------|
| `access.log` | Все HTTP-запросы к серверу |
| `error.log` | Ошибки Nginx |

#### Действия с логами

- **⬇️ Скачать** — получить конкретный лог как файл (в боте — отправляется в чат, в Web UI — скачивается в браузер)
- **🗑 Очистить один** — обнуляет содержимое конкретного файла (файл остаётся)
- **🧹 Очистить все** — обнуляет все `.log` файлы разом

#### Автоматическая очистка

Настраивается через `Auto log cleanup interval`:

| Интервал | Описание |
|---------|----------|
| Off (0) | Автоочистка выключена (по умолчанию) |
| 24 часа | Ежедневная очистка |
| 3 дня | Раз в 3 дня |
| 7 дней | Еженедельная очистка |
| 30 дней | Ежемесячная очистка |

---

### 🚫 Блокировка IP (IP Ban)

#### Принцип работы

Список заблокированных IP хранится в `nginx/.banned_ips.json`. При каждом изменении списка автоматически:
1. Перегенерируется конфиг Nginx (`nginx/conf.d/singbox.conf`) — в него добавляются директивы `deny ip;`
2. Nginx перезагружается (`nginx -s reload`)

Заблокированный IP получает ответ `403 Forbidden` на любой запрос.

#### Ручная блокировка

1. Ввести IP-адрес (формат `1.2.3.4`)
2. Указать причину (опционально)
3. Нажать `🚫 Ban` — блокировка вступает в силу немедленно

#### Автоматический анализ логов

Кнопка `🔍 Scan logs` / `Analyze logs` сканирует `nginx/logs/access.log` и ищет подозрительные IP по двум критериям:

1. **Высокая частота запросов** — более 30 запросов от одного IP (порог настраивается)
2. **Сканирующие паттерны** — обращения к характерным путям:
   - `.php`, `.asp`, `.env`, `.git`, `.bak` — попытки найти уязвимые файлы
   - `xmlrpc`, `wp-login`, `wp-admin`, `phpmyadmin` — сканирование CMS
   - `cgi-bin`, `shell`, `eval`, `passwd`, `/proc/self` — попытки эксплойтов
   - HTTP-методы `CONNECT`, `PROPFIND`, `TRACE`, `OPTIONS` — нетипичные запросы

После анализа показывается список с IP, количеством запросов и причиной. Можно:
- Забанить всех найденных одной кнопкой (`🚫 Ban all N IPs`)
- Или ничего не делать (анализ не баннит автоматически)

**Белый список (никогда не баннятся):**
- IP-диапазоны Telegram (для корректной работы webhook-режима)

#### Управление списком

- **✕ Unban** — разблокировать IP
- **🧹 Clear auto-bans** — удалить только автоматически найденные записи (ручные остаются)
- Тип каждой записи виден в списке: `✏️` — ручная блокировка, `🤖` — автоматическая

---

### ⚙️ Фоновый планировщик

Планировщик запускается автоматически при старте приложения как asyncio-задача и работает всё время жизни контейнера. Каждые **5 минут** проверяет:

1. Не пора ли делать автобэкап (сравнивает `now - last_backup_at >= backup_auto_hours * 3600`)
2. Не пора ли чистить логи (аналогично)

Если контейнер был перезапущен — планировщик восстанавливает настройки из базы данных и продолжает работу с учётом времени последнего выполнения.

---
""",
    "en": """
### What it is

The **Maintenance** section provides tools for automatic and manual server upkeep. Available in the Telegram bot (`🔧 Maintenance` button) and Web UI (`🔧 Maintenance` menu item).

---

### 💾 Backup

#### What's included

| File | Contents |
|------|----------|
| `config.json` | Sing-Box configuration (inbounds, routes, keys) |
| `app.db` | SQLite database (clients, admins, settings, audit logs) |

#### Manual backup

- **In bot:** `💾 Backup now` button — ZIP is sent directly to the chat
- **In Web UI:** `⬇️ Download ZIP` — browser downloads the archive; `📤 Send to admins` — sends ZIP to all Telegram admins

#### Scheduled auto-backup

Configure via `⏱ Auto-backup interval`:

| Interval | Description |
|---------|-------------|
| Off (0) | Disabled (default) |
| 6 hours | Every 6 hours |
| 12 hours | Twice a day |
| 24 hours | Once a day |
| 48 hours | Every two days |
| 7 days | Weekly |

When triggered, the scheduler creates a ZIP and **automatically sends it to all Telegram admins**.

**Setting storage:** `AppSetting` table, key `backup_auto_hours`. Restored on container restart.

---

### 📋 Log Management

#### Available logs

All `.log` files from `nginx/logs/`:

| File | Contents |
|------|----------|
| `access.log` | All HTTP requests to the server |
| `error.log` | Nginx errors |

#### Actions

- **⬇️ Download** — get the log as a file (sent to chat in bot, downloaded in browser in Web UI)
- **🗑 Clear one** — truncate a specific log file (file remains)
- **🧹 Clear all** — truncate all `.log` files at once

#### Auto-cleanup schedule

| Interval | Description |
|---------|-------------|
| Off (0) | Disabled (default) |
| 24 hours | Daily cleanup |
| 3 days | Every 3 days |
| 7 days | Weekly |
| 30 days | Monthly |

---

### 🚫 IP Ban

#### How it works

The ban list is stored in `nginx/.banned_ips.json`. On every change:
1. Nginx config is regenerated with `deny ip;` directives for each banned IP
2. Nginx is reloaded (`nginx -s reload`)

Banned IPs receive `403 Forbidden` for all requests.

#### Manual ban

1. Enter an IP address (`1.2.3.4` format)
2. Optionally provide a reason
3. Click `🚫 Ban` — takes effect immediately

#### Auto-analyze logs

`🔍 Scan logs` / `Analyze logs` scans `nginx/logs/access.log` for suspicious IPs based on:

1. **High request rate** — more than 30 requests from one IP (threshold configurable)
2. **Scan patterns** — requests to known probe paths:
   - `.php`, `.asp`, `.env`, `.git`, `.bak` — file vulnerability probing
   - `xmlrpc`, `wp-login`, `wp-admin`, `phpmyadmin` — CMS scanning
   - `cgi-bin`, `shell`, `eval`, `passwd`, `/proc/self` — exploit attempts
   - HTTP methods `CONNECT`, `PROPFIND`, `TRACE`, `OPTIONS` — unusual methods

Results are shown with IP, request count, and reason. You can:
- Ban all found IPs at once (`🚫 Ban all N IPs`)
- Or do nothing (analysis never bans automatically)

**Whitelist (never banned):**
- Telegram IP ranges (for webhook mode)

#### Managing the list

- **✕ Unban** — remove an IP from the ban list
- **🧹 Clear auto-bans** — remove only auto-added entries (manual ones remain)
- Entry type is shown in the list: `✏️` manual, `🤖` automatic

---

### ⚙️ Background Scheduler

The scheduler starts automatically with the application as an asyncio task and runs for the container's lifetime. Every **5 minutes** it checks:

1. Is it time for an auto-backup? (compares `now - last_backup_at >= backup_auto_hours * 3600`)
2. Is it time for log cleanup? (same logic)

If the container was restarted, the scheduler restores settings from the database and continues, accounting for the last execution time.
""",
}

_DOCS["cli"] = {
    "title": {"ru": "💻 Управление с сервера (CLI)", "en": "💻 Server Management (CLI)"},
    "ru": """
# CLI — Управление с сервера / Server Management CLI

---



### Что это такое

После установки на VPS автоматически появляется команда `singbox-ui-bot`. Её можно вызвать прямо в терминале — откроется интерактивное меню управления сервером.

```
singbox-ui-bot
```

Это удобно когда:
- Telegram недоступен и Web UI не открывается
- Нужно быстро сделать бэкап перед изменениями
- Нужно полностью очистить сервер
- Нужно посмотреть логи или перезапустить контейнеры

---

### Интерактивное меню

```
╔══════════════════════════════════╗
║      singbox-ui-bot  CLI         ║
╚══════════════════════════════════╝

  1) 📊 Status
  2) 💾 Backup
  3) 📋 Logs
  4) 🔄 Restart
  5) ⬆️  Update
  6) 🧹 Clear logs
  7) 🗑  Uninstall (cleanup server)
  0) Exit
```

---

### Прямые команды (без меню)

Можно передавать команду аргументом — меню не показывается:

```bash
singbox-ui-bot status     # статус контейнеров
singbox-ui-bot backup     # создать бэкап
singbox-ui-bot logs       # просмотр логов
singbox-ui-bot restart    # перезапустить контейнеры
singbox-ui-bot update     # обновить до последней версии
singbox-ui-bot uninstall  # полная очистка сервера
```

---

### Описание каждой команды

#### 📊 Status
Показывает:
- Статус всех Docker-контейнеров (app, singbox, nginx, adguard)
- Суммарный размер папки установки
- Размер базы данных `app.db`
- Размер каждого файла логов Nginx

```bash
singbox-ui-bot status
```

---

#### 💾 Backup
Создаёт ZIP-архив в домашней папке (`~/singbox-backup_YYYY-MM-DD_HH-MM-SS.zip`).

Что входит в архив:

| Файл | Содержимое |
|------|-----------|
| `config.json` | Конфигурация Sing-Box (inbounds, routes, ключи) |
| `app.db` | База данных (клиенты, настройки, аудит) |
| `.env` | Секреты: токен бота, пароли, SECRET_KEY |

```bash
singbox-ui-bot backup
# → ~/singbox-backup_2026-03-02_14-30-00.zip
```

> Всегда делай бэкап перед обновлением или экспериментами.

---

#### 📋 Logs
Интерактивный выбор контейнера, затем `docker compose logs -f`:

```
Which container?
  1) app (bot + API)
  2) singbox
  3) nginx
  4) adguard
  5) All (interleaved)
```

Выход из логов: `Ctrl+C`

```bash
singbox-ui-bot logs
```

---

#### 🔄 Restart
Интерактивный выбор — перезапустить всё или конкретный контейнер:

```
What to restart?
  1) All containers (recommended)
  2) app only (bot + API)
  3) singbox only
  4) nginx only
```

```bash
singbox-ui-bot restart
```

---

#### ⬆️ Update
Обновляет проект до последней версии из GitHub:

1. Создаёт автоматический бэкап (на случай проблем)
2. Делает `git pull origin main`
3. Пересобирает контейнер `app` (`docker compose build app`)
4. Перезапускает `app`

Данные (config.json, app.db, .env) **не затрагиваются**.

```bash
singbox-ui-bot update
```

---

#### 🧹 Clear logs
Показывает список файлов логов с размером и предлагает очистить все разом (обнулить, не удалить).

```bash
singbox-ui-bot   # → выбрать пункт 6
```

---

#### 🗑 Uninstall — Полная очистка сервера

Удаляет **всё**, что было установлено:

1. **Предлагает сделать бэкап** — сохранить данные перед удалением
2. Требует ввести `yes` для подтверждения (защита от случайного запуска)
3. Останавливает и удаляет все контейнеры + Docker volumes
4. Удаляет Docker-образы проекта
5. Убирает записи из crontab (авто-продление SSL)
6. Удаляет папку `/opt/singbox-ui-bot`
7. Удаляет сам файл `/usr/local/bin/singbox-ui-bot`

```bash
singbox-ui-bot uninstall
```

После этого сервер возвращается в состояние "до установки".

> Бэкап перед удалением сохраняется в `~/singbox-backup_*.zip` — его нужно скачать вручную через `scp` или SFTP, если он понадобится.

---

### Как скачать бэкап с сервера

```bash
# С локального компьютера:
scp root@твой-ip:~/singbox-backup_*.zip ./

# Или через rsync:
rsync -avz root@твой-ip:~/singbox-backup_*.zip ./
```

---

### Как переустановить после удаления

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

Если есть бэкап — после установки можно восстановить данные:
```bash
# Скопировать config.json обратно:
cp ./config.json /opt/singbox-ui-bot/config/sing-box/config.json

# Скопировать базу данных:
cp ./app.db /opt/singbox-ui-bot/data/app.db

# Перезапустить:
singbox-ui-bot restart
```

---
""",
    "en": """
### What is it

After installation, the command `singbox-ui-bot` becomes available on the VPS. Run it in a terminal to get an interactive management menu.

```
singbox-ui-bot
```

Useful when:
- Telegram is unavailable and Web UI is unreachable
- You need a quick backup before making changes
- You need to fully clean the server
- You need to check logs or restart containers

---

### Interactive Menu

```
╔══════════════════════════════════╗
║      singbox-ui-bot  CLI         ║
╚══════════════════════════════════╝

  1) 📊 Status
  2) 💾 Backup
  3) 📋 Logs
  4) 🔄 Restart
  5) ⬆️  Update
  6) 🧹 Clear logs
  7) 🗑  Uninstall (cleanup server)
  0) Exit
```

---

### Direct Commands (no menu)

Pass a subcommand to skip the menu:

```bash
singbox-ui-bot status     # container status
singbox-ui-bot backup     # create backup
singbox-ui-bot logs       # view logs
singbox-ui-bot restart    # restart containers
singbox-ui-bot update     # pull & rebuild
singbox-ui-bot uninstall  # full server cleanup
```

---

### Command Reference

#### 📊 Status
Shows:
- Docker container status (app, singbox, nginx, adguard)
- Total install directory size
- Database (`app.db`) size
- Nginx log file sizes

---

#### 💾 Backup
Creates `~/singbox-backup_YYYY-MM-DD_HH-MM-SS.zip` containing:

| File | Contents |
|------|----------|
| `config.json` | Sing-Box configuration |
| `app.db` | Database (clients, settings, audit) |
| `.env` | Secrets: bot token, passwords, SECRET_KEY |

> Always backup before updates or experiments.

---

#### 📋 Logs
Interactive container selection, then `docker compose logs -f`. Exit with `Ctrl+C`.

---

#### 🔄 Restart
Interactive selection — restart all or a specific container.

---

#### ⬆️ Update
1. Creates an automatic backup
2. Runs `git pull origin main`
3. Rebuilds the `app` container
4. Restarts `app`

Your data (config.json, app.db, .env) is **not affected**.

---

#### 🗑 Uninstall — Full Server Cleanup

1. **Offers to create a backup** first
2. Requires typing `yes` to confirm
3. Stops and removes all containers + Docker volumes
4. Removes Docker images
5. Removes crontab entries (SSL auto-renewal)
6. Deletes `/opt/singbox-ui-bot`
7. Deletes `/usr/local/bin/singbox-ui-bot`

The server is returned to its pre-installation state.

---

### Downloading a Backup from the Server

```bash
# From your local machine:
scp root@your-server-ip:~/singbox-backup_*.zip ./
```

---

### Reinstalling After Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

To restore from a backup after reinstalling:
```bash
cp ./config.json /opt/singbox-ui-bot/config/sing-box/config.json
cp ./app.db /opt/singbox-ui-bot/data/app.db
singbox-ui-bot restart
```
""",
}


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/", summary="List available documentation")
async def list_docs(lang: str = Query("ru", regex="^(ru|en)$"), _=Depends(require_any_auth)):
    return [
        {"id": doc_id, "title": meta["title"].get(lang, meta["title"]["en"])}
        for doc_id, meta in _DOCS.items()
    ]


@router.get("/{doc_id}", response_class=PlainTextResponse, summary="Get doc content")
async def get_doc(doc_id: str, lang: str = Query("ru", regex="^(ru|en)$"), _=Depends(require_any_auth)):
    if doc_id not in _DOCS:
        raise HTTPException(status_code=404, detail=f"Doc '{doc_id}' not found")
    content = _DOCS[doc_id].get(lang) or _DOCS[doc_id]["ru"]
    return content.strip()