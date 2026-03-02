# Maintenance / Обслуживание

---

## 🇷🇺 Русский

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

## 🇬🇧 English

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
