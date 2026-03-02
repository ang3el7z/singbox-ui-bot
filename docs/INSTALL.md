# Установка / Installation Guide

---

## 🇷🇺 Русский

### Требования к серверу

| Компонент | Минимум | Рекомендуется |
|-----------|---------|--------------|
| ОС | Ubuntu 22.04 / Debian 12 | Ubuntu 24.04 LTS |
| CPU | 1 ядро | 2 ядра |
| RAM | 512 МБ | 1 ГБ |
| Диск | 10 ГБ | 20 ГБ |
| Docker | 24+ | последняя версия |
| Docker Compose | v2+ | последняя версия |
| Домен | обязательно | A-запись → IP сервера |
| Порты открыты | 80, 443, 53 (TCP+UDP) | + порты VPN (443, 8443 и т.д.) |

> **Важно:** домен должен быть настроен **до** установки. certbot не сможет выпустить SSL, если A-запись не смотрит на IP сервера.

---

### Быстрая установка (один командой)

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

Скрипт автоматически клонирует репозиторий, задаст вопросы и поднимет всё.

---

### Ручная установка (шаг за шагом)

#### 1. Установить Docker

```bash
# Обновить пакеты
apt-get update && apt-get upgrade -y

# Установить Docker
curl -fsSL https://get.docker.com | bash
systemctl enable docker
systemctl start docker

# Проверить
docker --version
docker compose version
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

Обязательные поля:

```env
# Telegram — получить у @BotFather
BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Твой Telegram ID — узнать у @userinfobot
ADMIN_IDS=123456789

# Домен
DOMAIN=vpn.example.com
EMAIL=admin@example.com

# Секреты — замени на случайные строки (минимум 32 символа)
INTERNAL_TOKEN=сюда_случайную_строку_32_символа
JWT_SECRET=сюда_другую_случайную_строку_32с
FEDERATION_SECRET=ещё_одна_случайная_строка_32с
SECRET_KEY=и_ещё_одна_случайная_строка_32с

# Пароли — измени на сложные
WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=замени_на_сложный_пароль
ADGUARD_PASSWORD=другой_сложный_пароль
```

Сгенерировать случайные секреты:
```bash
openssl rand -hex 32  # запустить 4 раза для каждого поля
```

#### 4. Создать необходимые директории

```bash
mkdir -p nginx/conf.d nginx/logs nginx/override nginx/htpasswd nginx/certs
mkdir -p config/sing-box/templates
mkdir -p data subs
```

#### 5. Выпустить SSL сертификат

```bash
# Остановить nginx если запущен
systemctl stop nginx 2>/dev/null || true

# Получить сертификат (замени domain и email)
certbot certonly --standalone -d vpn.example.com \
  --email admin@example.com --agree-tos --non-interactive

# Скопировать в папку проекта
DOMAIN="vpn.example.com"
mkdir -p nginx/certs/live/$DOMAIN
cp -L /etc/letsencrypt/live/$DOMAIN/fullchain.pem nginx/certs/live/$DOMAIN/
cp -L /etc/letsencrypt/live/$DOMAIN/privkey.pem nginx/certs/live/$DOMAIN/
chmod 644 nginx/certs/live/$DOMAIN/fullchain.pem
chmod 600 nginx/certs/live/$DOMAIN/privkey.pem
```

#### 6. Настроить начальный конфиг Nginx

Создай файл `nginx/conf.d/singbox.conf`:

```nginx
server {
    listen 80;
    server_name vpn.example.com;
    server_tokens off;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /api/ {
        proxy_pass http://app:8080/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /web/ {
        alias /var/www/web/;
        try_files $uri $uri/ /web/index.html;
    }

    location = / {
        try_files /index.html @auth;
    }

    location @auth {
        auth_basic "Restricted Content";
        auth_basic_user_file /etc/nginx/htpasswd/.htpasswd;
        try_files /dev/null =403;
    }
}
```

#### 7. Запустить контейнеры

```bash
cd /opt/singbox-ui-bot
docker compose up -d --build
```

Проверить статус:
```bash
docker compose ps
docker compose logs -f app
```

---

### Первые шаги после установки

#### Шаг 1 — Проверить бота

Открой Telegram, найди своего бота, отправь `/start`. Должно появиться главное меню с кнопками.

Если бот не отвечает:
```bash
docker compose logs app --tail 50
```

#### Шаг 2 — Настроить Nginx через бота

1. `/menu` → 🌐 **Nginx** → ⚙️ **Configure & Reload**
2. Бот сгенерирует полный конфиг из шаблона (с HTTPS, скрытыми путями, заглушкой) и перезагрузит Nginx

Если SSL уже есть — Nginx сразу перейдёт на HTTPS.

#### Шаг 3 — Добавить первый inbound

1. `/menu` → 🔌 **Inbounds** → ➕ **Add Inbound**
2. Выбрать протокол: рекомендуется `VLESS Reality` (не детектируется)
3. Ввести тег: например `vless-main`
4. Ввести порт: `443`
5. Reality-ключи сгенерируются автоматически

#### Шаг 4 — Добавить первого клиента

1. `/menu` → 👥 **Clients** → ➕ **Add**
2. Ввести имя клиента
3. Выбрать inbound (только что созданный)
4. Лимит трафика в ГБ (0 = безлимит)
5. Срок действия в днях (0 = бессрочно)
6. Нажать **📄 Download config** — получишь файл `config.json`
7. Импортировать в Sing-Box приложение на телефоне/ПК

#### Шаг 5 — Открыть Web UI

Перейди на `https://vpn.example.com/web/`  
Логин: `admin`  
Пароль: значение `WEB_ADMIN_PASSWORD` из `.env`

> **Сразу поменяй пароль:** Admin → Change Password

---

### Настройка автообновления SSL

```bash
# Добавить хук для копирования сертификата после продления
cat > /etc/letsencrypt/renewal-hooks/deploy/copy-to-singbox.sh << 'EOF'
#!/bin/bash
DOMAIN="vpn.example.com"   # замени на свой домен
CERT_DST="/opt/singbox-ui-bot/nginx/certs/live/$DOMAIN"
mkdir -p "$CERT_DST"
cp -L "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "$CERT_DST/fullchain.pem"
cp -L "/etc/letsencrypt/live/$DOMAIN/privkey.pem" "$CERT_DST/privkey.pem"
chmod 644 "$CERT_DST/fullchain.pem"
chmod 600 "$CERT_DST/privkey.pem"
docker exec singbox_nginx nginx -s reload 2>/dev/null || true
echo "SSL renewed and copied for $DOMAIN"
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/copy-to-singbox.sh

# Добавить cron для автопродления
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet") | sort -u | crontab -
```

---

### Обновление проекта

```bash
cd /opt/singbox-ui-bot
bash scripts/update.sh
```

Скрипт создаёт резервную копию, делает `git pull` и пересобирает контейнеры.

Вручную:
```bash
cd /opt/singbox-ui-bot
# Создать бэкап перед обновлением
cp config/sing-box/config.json config/sing-box/config.json.bak
cp data/app.db data/app.db.bak

git pull origin main
docker compose up -d --build
```

---

### Файрвол (UFW)

```bash
# Базовые правила
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp          # SSH (или твой SSH порт)
ufw allow 80/tcp          # HTTP (нужен для certbot)
ufw allow 443/tcp         # HTTPS
ufw allow 53/tcp          # DNS
ufw allow 53/udp          # DNS
# Дополнительные VPN-порты (если используешь)
ufw allow 8443/tcp        # Trojan/Hysteria2
ufw allow 10443/udp       # Hysteria2 UDP
ufw --force enable
```

---

### Структура файлов после установки

```
/opt/singbox-ui-bot/
├── .env                            ← секреты (chmod 600, никогда не публиковать!)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
│
├── api/                            ← FastAPI бэкенд (бизнес-логика)
│   ├── main.py                     ← точка входа FastAPI
│   ├── config.py                   ← настройки из .env
│   ├── database.py                 ← SQLAlchemy модели
│   ├── deps.py                     ← JWT + auth зависимости
│   ├── routers/                    ← REST-эндпоинты
│   └── services/                   ← singbox, adguard, nginx, federation
│
├── bot/                            ← Telegram бот (UI-слой)
│   ├── main.py                     ← запуск aiogram + FastAPI
│   ├── api_client.py               ← HTTP-клиент к /api/*
│   ├── handlers/                   ← обработчики команд и кнопок
│   ├── keyboards/                  ← InlineKeyboard клавиатуры
│   └── middleware/                 ← auth, rate limit
│
├── web/                            ← Web UI (без сборки, чистый JS)
│   ├── index.html                  ← SPA с Alpine.js
│   ├── js/api.js                   ← fetch-обёртки
│   ├── js/app.js                   ← Alpine.js компоненты
│   └── css/style.css               ← стили
│
├── config/
│   └── sing-box/
│       ├── config.json             ← ЖИВОЙ конфиг (изменяется ботом!)
│       └── templates/              ← шаблоны inbound для справки
│
├── nginx/
│   ├── templates/main.conf.j2      ← Jinja2 шаблон конфига Nginx
│   ├── conf.d/singbox.conf         ← сгенерированный конфиг
│   ├── override/                   ← загруженный пользователем сайт
│   ├── htpasswd/.htpasswd          ← случайный пароль для 401-заглушки
│   ├── certs/                      ← SSL сертификаты
│   └── logs/                       ← access.log, error.log
│
├── data/
│   └── app.db                      ← SQLite база данных
│
├── subs/                           ← файлы подписок клиентов
│
├── docs/                           ← документация
└── scripts/
    ├── install.sh                  ← скрипт установки
    └── update.sh                   ← скрипт обновления
```

---

### Полезные команды

```bash
# Посмотреть логи
docker compose logs -f app          # FastAPI + бот
docker compose logs -f singbox      # Sing-Box VPN ядро
docker compose logs -f nginx        # Nginx
docker compose logs -f adguard      # AdGuard Home

# Перезапустить сервис
docker compose restart app
docker compose restart singbox

# Зайти в контейнер
docker exec -it singbox_app bash
docker exec -it singbox_core sh

# Проверить конфиг Sing-Box
docker exec singbox_core sing-box check -c /etc/sing-box/config.json

# Просмотр текущего конфига
cat /opt/singbox-ui-bot/config/sing-box/config.json | jq .

# Резервная копия вручную
tar -czf backup-$(date +%Y%m%d).tar.gz \
  /opt/singbox-ui-bot/.env \
  /opt/singbox-ui-bot/config/sing-box/config.json \
  /opt/singbox-ui-bot/data/app.db
```

---

### Решение частых проблем

#### Бот не отвечает
```bash
# Проверить логи
docker compose logs app --tail 100

# Частые причины:
# - Неверный BOT_TOKEN в .env
# - ADMIN_IDS не совпадает с твоим Telegram ID
```

#### Nginx отдаёт 502 Bad Gateway
```bash
# Проверить, запущен ли app-контейнер
docker compose ps
docker compose logs app --tail 30

# Проверить, что порт 8080 слушается внутри контейнера
docker exec singbox_app ss -tlnp | grep 8080
```

#### Sing-Box не запускается
```bash
# Проверить валидность конфига
docker exec singbox_core sing-box check -c /etc/sing-box/config.json

# Посмотреть ошибку
docker compose logs singbox --tail 50
```

#### SSL сертификат не выпускается
```bash
# Проверить DNS
nslookup vpn.example.com
# Должен вернуть IP твоего сервера

# Проверить доступность порта 80
curl -I http://vpn.example.com
# Должен вернуть ответ (даже 401 — это нормально)

# Порт 80 должен быть свободен во время certbot certonly --standalone
systemctl stop nginx 2>/dev/null; \
certbot certonly --standalone -d vpn.example.com -m email@example.com --agree-tos -n
```

#### AdGuard не работает как DNS
```bash
# Проверить, что порт 53 не занят системным resolved
systemctl stop systemd-resolved
systemctl disable systemd-resolved
echo "nameserver 127.0.0.1" > /etc/resolv.conf

# Перезапустить AdGuard
docker compose restart adguard
```

---

## 🇬🇧 English

### Server Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Ubuntu 22.04 / Debian 12 | Ubuntu 24.04 LTS |
| CPU | 1 core | 2 cores |
| RAM | 512 MB | 1 GB |
| Disk | 10 GB | 20 GB |
| Docker | 24+ | latest |
| Docker Compose | v2+ | latest |
| Domain | required | A-record → server IP |
| Open ports | 80, 443, 53 (TCP+UDP) | + VPN ports (443, 8443 etc.) |

> **Important:** the domain must be configured **before** installation. certbot cannot issue SSL if the A-record doesn't point to your server's IP.

---

### Quick Install (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/ang3el7z/singbox-ui-bot/main/scripts/install.sh | bash
```

The script will automatically clone the repository, ask questions, and bring everything up.

---

### Manual Installation (step by step)

#### 1. Install Docker

```bash
apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com | bash
systemctl enable docker && systemctl start docker
docker --version && docker compose version
```

#### 2. Clone the repository

```bash
git clone https://github.com/ang3el7z/singbox-ui-bot.git /opt/singbox-ui-bot
cd /opt/singbox-ui-bot
```

#### 3. Configure .env

```bash
cp .env.example .env
nano .env
```

Required fields:

```env
BOT_TOKEN=1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx   # from @BotFather
ADMIN_IDS=123456789                                     # your Telegram ID from @userinfobot
DOMAIN=vpn.example.com
EMAIL=admin@example.com

# Generate with: openssl rand -hex 32
INTERNAL_TOKEN=<32+ char random string>
JWT_SECRET=<32+ char random string>
FEDERATION_SECRET=<32+ char random string>
SECRET_KEY=<32+ char random string>

WEB_ADMIN_USER=admin
WEB_ADMIN_PASSWORD=<strong password>
ADGUARD_PASSWORD=<strong password>
```

#### 4. Create required directories

```bash
mkdir -p nginx/conf.d nginx/logs nginx/override nginx/htpasswd nginx/certs
mkdir -p config/sing-box/templates
mkdir -p data subs
```

#### 5. Issue SSL certificate

```bash
systemctl stop nginx 2>/dev/null || true
certbot certonly --standalone -d vpn.example.com \
  --email admin@example.com --agree-tos --non-interactive

DOMAIN="vpn.example.com"
mkdir -p nginx/certs/live/$DOMAIN
cp -L /etc/letsencrypt/live/$DOMAIN/fullchain.pem nginx/certs/live/$DOMAIN/
cp -L /etc/letsencrypt/live/$DOMAIN/privkey.pem nginx/certs/live/$DOMAIN/
chmod 644 nginx/certs/live/$DOMAIN/fullchain.pem
chmod 600 nginx/certs/live/$DOMAIN/privkey.pem
```

#### 6. Start containers

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

---

### First Steps After Installation

1. **Open Telegram** → find your bot → send `/start` → main menu should appear
2. **/menu → 🌐 Nginx → Configure & Reload** — generates full Nginx config with HTTPS and hidden paths
3. **/menu → 🔌 Inbounds → Add** — add VLESS Reality on port 443 (keys auto-generated)
4. **/menu → 👥 Clients → Add** — create a user, download `config.json`, import into Sing-Box app
5. **https://vpn.example.com/web/** — Web UI, login with `admin` / your password

---

### Updating

```bash
cd /opt/singbox-ui-bot && bash scripts/update.sh
```

Or manually:
```bash
git pull origin main
docker compose up -d --build
```

---

### Useful Commands

```bash
# Logs
docker compose logs -f app          # FastAPI + bot
docker compose logs -f singbox      # Sing-Box VPN core
docker compose logs -f nginx        # Nginx access/error
docker compose logs -f adguard      # AdGuard Home

# Restart
docker compose restart app
docker compose restart singbox

# Validate Sing-Box config
docker exec singbox_core sing-box check -c /etc/sing-box/config.json

# Manual backup
tar -czf backup-$(date +%Y%m%d).tar.gz \
  /opt/singbox-ui-bot/.env \
  /opt/singbox-ui-bot/config/sing-box/config.json \
  /opt/singbox-ui-bot/data/app.db
```

---

### Troubleshooting

| Symptom | Check | Fix |
|---------|-------|-----|
| Bot not responding | `docker compose logs app --tail 100` | Verify BOT_TOKEN and ADMIN_IDS in .env |
| Nginx 502 | `docker compose ps` | Ensure `app` container is running |
| Sing-Box not starting | `docker compose logs singbox` | Run `sing-box check -c config.json` |
| SSL not issued | `nslookup vpn.example.com` | Ensure DNS A-record points to your server |
| AdGuard DNS not working | `ss -tlnp \| grep 53` | Stop systemd-resolved, restart adguard |
| Web UI shows blank page | Browser console errors | Check that `/web/` is served by Nginx |
