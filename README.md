# Singbox UI Bot

Telegram-бот для управления Sing-Box VPN серверами. Поддерживает AdGuard Home, гибкую маршрутизацию, Nginx с сайтами-заглушками, и федерацию ботов для построения многоуровневых VPN-цепочек.

## Возможности

| Раздел | Функции |
|--------|---------|
| 🖥 **Сервер** | Статус, рестарт, логи Sing-Box |
| 👥 **Клиенты** | CRUD, QR-коды, подписки (Sing-Box/Clash), статистика трафика |
| 📡 **Inbounds** | Все протоколы: VLESS Reality/WS, VMess, Shadowsocks, Trojan, Hysteria2, TUIC |
| 🔀 **Маршрутизация** | Домены, IP/CIDR, GeoSite, GeoIP, Rule Sets, импорт/экспорт |
| 🛡 **AdGuard Home** | Управление DNS, правила фильтрации, статистика, синхронизация клиентов |
| 🌐 **Nginx** | Конфигурация, SSL Let's Encrypt, сайты-заглушки, скрытые пути |
| 🔗 **Федерация** | Соединение ботов в цепочки (Bridge/Node), HMAC-авторизация |
| ⚙️ **Настройки** | Администраторы, бэкап, audit-лог |

## Быстрая установка

```bash
# На сервере Debian 12 / Ubuntu 24.04
git clone https://github.com/ang3el7z/singbox-ui-bot.git /opt/singbox-ui-bot
sudo bash /opt/singbox-ui-bot/scripts/install.sh
```

Скрипт автоматически:
1. Установит Docker, certbot, UFW
2. Спросит домен, токен бота, email
3. Получит SSL-сертификат Let's Encrypt
4. Сгенерирует безопасный `.env`
5. Запустит все контейнеры

## Ручная установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/ang3el7z/singbox-ui-bot.git
cd singbox-ui-bot

# 2. Создать .env из примера
cp .env.example .env
nano .env   # Заполнить BOT_TOKEN, ADMIN_IDS, DOMAIN, EMAIL

# 3. Запустить
docker compose up -d --build
```

## Архитектура

```
┌─────────────────────────────────────────────┐
│              Docker Compose                  │
│                                             │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │  nginx  │  │   bot    │  │    sui    │  │
│  │  :80    │──│  :8080   │──│  :2095   │  │
│  │  :443   │  │ (aiogram │  │ (Sing-Box │  │
│  └────┬────┘  │  +FastAPI│  │  Panel)  │  │
│       │       └──────────┘  └───────────┘  │
│       │       ┌──────────┐                 │
│       └───────│ adguard  │                 │
│               │  :3000   │                 │
│               └──────────┘                 │
└─────────────────────────────────────────────┘
```

## Федерация ботов

Позволяет соединять несколько серверов в цепочки:

```
Пользователь → Нод A → Нод B → Интернет
                ↓ (bridge)
             Нод C (альтернативный выход)
```

**Добавление ноды:**
1. На ноде B: убедитесь что `FEDERATION_SECRET` установлен
2. В боте ноды A: Федерация → Добавить ноду → URL + секрет ноды B
3. Федерация → Создать Bridge → выбрать ноды в нужном порядке

## Nginx и сайт-заглушка

Nginx настраивается с **скрытыми путями** (hash-based URLs):

| Сервис | Путь |
|--------|------|
| Панель s-ui | `/{hash12}/panel/` |
| Подписки | `/{hash12}/sub/` |
| AdGuard | `/{hash12}/adg/` |
| Federation API | `/{hash12}/api/` |

Корневой URL `/` отображает сайт-заглушку. Доступные темы:
- `default` — минималистичный тёмный
- `business` — страница технических работ
- `blog` — имитация личного блога
- `custom` — загрузите свой HTML через бота

## Конфигурация (.env)

```env
BOT_TOKEN=токен_от_botfather
ADMIN_IDS=123456789          # Telegram ID администраторов через запятую
DOMAIN=vpn.example.com
EMAIL=admin@example.com
STUB_THEME=default            # Тема заглушки
FEDERATION_SECRET=секрет_32+  # Общий секрет для HMAC
BOT_LANG=ru                   # Язык: ru / en
```

## Безопасность

- Доступ к боту только для whitelist Telegram ID
- s-ui API: Bearer-токены, не пароли
- Federation API: HMAC-SHA256 подпись + 5-минутное окно временной метки
- Nginx: скрытые пути через sha256 от SECRET_KEY
- Audit Log: все действия администраторов сохраняются в БД
- Rate limiting: 30 запросов / 60 сек на пользователя
- Секреты только в `.env` (chmod 600), не в коде

## Обновление

```bash
sudo bash /opt/singbox-ui-bot/scripts/update.sh
```

## Структура проекта

```
singbox-ui-bot/
├── bot/
│   ├── main.py                 # Точка входа (aiogram + FastAPI)
│   ├── config.py               # Настройки из .env
│   ├── database.py             # SQLAlchemy модели (SQLite)
│   ├── texts.py                # i18n строки (RU/EN)
│   ├── utils.py                # Утилиты (QR, форматирование)
│   ├── handlers/               # Telegram хэндлеры
│   │   ├── start.py            # /start, главное меню
│   │   ├── server.py           # Статус, логи, рестарт
│   │   ├── clients.py          # Управление клиентами
│   │   ├── inbounds.py         # Управление inbounds
│   │   ├── routing.py          # Правила маршрутизации
│   │   ├── adguard.py          # AdGuard Home
│   │   ├── nginx.py            # Nginx + заглушки
│   │   ├── federation.py       # Федерация ботов
│   │   └── admin.py            # Администраторы, бэкап
│   ├── keyboards/              # Inline клавиатуры
│   ├── services/
│   │   ├── sui_api.py          # HTTP-клиент s-ui API
│   │   ├── adguard_api.py      # HTTP-клиент AdGuard API
│   │   ├── nginx_service.py    # Генерация конфигов Nginx
│   │   └── federation_service.py # HMAC API + inter-bot
│   └── middleware/
│       ├── auth.py             # Admin whitelist check
│       └── rate_limit.py       # Rate limiting
├── nginx/
│   ├── templates/              # Jinja2 шаблоны конфигов
│   └── stubs/                  # HTML сайты-заглушки
├── scripts/
│   ├── install.sh              # Автоматическая установка
│   └── update.sh               # Обновление
├── configs/
│   └── singbox_templates/      # Шаблоны конфигов Sing-Box
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Лицензия

MIT
