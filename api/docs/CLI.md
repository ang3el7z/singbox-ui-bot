# CLI — Управление с сервера / Server Management CLI

---

## 🇷🇺 Русский

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

## 🇬🇧 English

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
