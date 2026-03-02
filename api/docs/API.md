# REST API Reference / Справочник REST API

---

## 🇷🇺 Русский

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
curl -X POST https://домен/api/auth/login \
  -H "Content-Type: application/json" \
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
curl https://домен/api/auth/me \
  -H "Authorization: Bearer eyJ..."
```

Ответ `200`:
```json
{"username": "admin", "id": 1}
```

#### `POST /api/auth/change-password` — Смена пароля

```bash
curl -X POST https://домен/api/auth/change-password \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
  -d '{"current_password": "old", "new_password": "newpass123"}'
```

Ответ `200`: `{"detail": "Password changed"}`

---

### 🖥 Server — Управление сервером

#### `GET /api/server/status` — Статус Sing-Box

```bash
curl https://домен/api/server/status \
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
curl -X POST https://домен/api/server/reload \
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
curl https://домен/api/clients/ \
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
curl -X POST https://домен/api/clients/ \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
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
curl -X PATCH https://домен/api/clients/1 \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
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
curl -X POST https://домен/api/inbounds/ \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
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
curl https://домен/api/routing/rules/domain \
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
curl -X POST https://домен/api/routing/rules \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
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
curl -X POST https://домен/api/routing/rule-sets \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
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
Требует: `DOMAIN` и `EMAIL` в `.env`, домен должен смотреть на сервер, порт 80 открыт.

#### `GET /api/nginx/paths` — Скрытые пути панелей

#### `GET /api/nginx/logs?lines=50` — Access-логи Nginx

#### `POST /api/nginx/override/upload` — Загрузить кастомный сайт

```bash
# Загрузить HTML
curl -X POST https://домен/api/nginx/override/upload \
  -H "Authorization: Bearer eyJ..." \
  -F "file=@/path/to/index.html"

# Загрузить ZIP
curl -X POST https://домен/api/nginx/override/upload \
  -H "Authorization: Bearer eyJ..." \
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
curl -X POST https://домен/api/federation/ \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
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
curl -X POST https://домен/api/federation/bridge \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
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
curl https://домен/api/admin/backup \
  -H "Authorization: Bearer eyJ..." \
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

## 🇬🇧 English

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
curl -X POST https://domain/api/auth/login \
  -H "Content-Type: application/json" \
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
