# Federation — Объединение серверов / Server Federation

---

## 🇷🇺 Русский

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
curl -X POST https://нода.example.com/federation/ping \
  -H "X-Federation-Timestamp: $(date +%s)" \
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

## 🇬🇧 English

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
