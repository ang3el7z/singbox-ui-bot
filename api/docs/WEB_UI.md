# Web UI — Веб-интерфейс / Web Interface

---

## 🇷🇺 Русский

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

**Вкладки:**
- **Rules** — таблица правил маршрутизации
- **Rule Sets** — подключённые наборы правил (remote rule sets)
- **Import / Export** — кнопки для JSON-бэкапа правил

**Таблица правил:**
| Столбец | Пример |
|---------|--------|
| Тип | `geosite`, `domain`, `ip_cidr`, ... |
| Значение | `ru`, `google.com`, `192.168.0.0/16` |
| Action | `direct`, `proxy`, `block`, `dns` |
| Действие | кнопка **Delete** |

**Добавление правила** (кнопка **+ Add Rule**):

Форма:
1. **Rule Type** — выпадающий список типов
2. **Value** — значение (домен, IP, geosite tag, и т.д.)
3. **Outbound** — куда направить трафик

**Rule Sets:**
Здесь можно добавить ссылку на внешний `.srs` файл — Sing-Box автоматически скачивает и обновляет его.

Пример правила: весь российский трафик напрямую:
- Тип: `geosite`
- Значение: `ru`
- Action: `direct`

**Экспорт/Импорт:**
- **Export** — скачать все правила в JSON
- **Import** — загрузить JSON с правилами (правила добавятся к существующим, не заменят)

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

**Таблица нод:**
| Поле | Значение |
|------|---------|
| Имя | `node-amsterdam` |
| URL | `https://amsterdam.example.com` |
| Роль | `node` / `bridge` |
| Статус | 🟢 Online / 🔴 Offline |
| Последний пинг | дата и время |
| Действия | Ping / Delete |

**Кнопки:**
- **+ Add Node** — форма добавления ноды
- **Ping All** — проверить доступность всех нод одновременно
- **Create Bridge** — форма создания multi-hop цепочки
- **Topology** — схема сети в виде дерева

**Топология:**
```
Master: vpn.example.com
├── node-amsterdam [node] 🟢
├── node-frankfurt [node] 🟢
└── node-london    [bridge] 🔴
```

Подробнее о федерации: [FEDERATION.md](./FEDERATION.md)

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

## 🇬🇧 English

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
| ⚙️ Settings | Timezone dropdown, bot language buttons, system status |
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
