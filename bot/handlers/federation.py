"""Federation — thin wrapper over /api/federation/"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from api.routers.settings_router import get_runtime
from bot.api_client import federation_api, APIError
from bot.keyboards.main import kb_back, kb_federation_menu, kb_nodes_list, kb_bridge_node_select

router = Router()


class AddNodeFSM(StatesGroup):
    name = State()
    url = State()
    secret = State()
    role = State()


class CreateBridgeFSM(StatesGroup):
    selecting = State()   # user selects nodes in chain order


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


@router.callback_query(F.data == "menu_federation")
async def cb_federation_menu(cq: CallbackQuery):
    try:
        nodes = await federation_api.list()
        active = sum(1 for n in nodes if n.get("is_active"))
        text = _txt(
            f"🌐 <b>Федерация</b> — узлов: {len(nodes)} ({active} онлайн)",
            f"🌐 <b>Federation</b> — nodes: {len(nodes)} ({active} online)",
        )
        mk = kb_federation_menu(nodes)
    except APIError as e:
        text = f"❌ {e.detail}"
        mk = kb_back("main_menu")
    await cq.message.edit_text(text, reply_markup=mk, parse_mode="HTML")


@router.callback_query(F.data == "federation_topology")
async def cb_federation_topology(cq: CallbackQuery):
    try:
        topo = await federation_api.topology()
        master = topo.get("master", _txt("этот сервер", "this server"))
        nodes = topo.get("nodes", [])
        lines = [f"🖥 <b>{master}</b> ({_txt('master', 'master')})"]
        for n in nodes:
            icon = "🟢" if n.get("is_active") else "🔴"
            lines.append(f"  └─ {icon} {n['name']} [{n['role']}] — {n['url']}")
        text = "\n".join(lines) or _txt("Нет узлов", "No nodes")
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_federation"))


@router.callback_query(F.data == "federation_secret")
async def cb_federation_secret(cq: CallbackQuery):
    try:
        data = await federation_api.local_secret()
        display_name = data.get("display_name", _txt("этот сервер", "this server"))
        lines = [
            f"<b>{display_name}</b>",
            "",
            _txt("Локальный секрет федерации:", "Local federation secret:"),
            f"<code>{data.get('secret', '')}</code>",
        ]
        if data.get("domain"):
            lines.extend(["", _txt(f"Домен: <code>{data['domain']}</code>", f"Domain: <code>{data['domain']}</code>")])
        elif data.get("public_url"):
            lines.extend(["", f"URL: <code>{data['public_url']}</code>"])
        lines.extend([
            "",
            _txt(
                "Используйте это значение на другом сервере в разделе Федерация -> Добавить узел -> Secret.",
                "Use this value on another server in Federation -> Add Node -> Secret.",
            ),
        ])
        text = "\n".join(lines)
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_federation"))


@router.callback_query(F.data == "federation_ping_all")
async def cb_federation_ping_all(cq: CallbackQuery):
    await cq.answer(_txt("Пингую…", "Pinging…"))
    try:
        results = await federation_api.ping_all()
        lines = [f"{'🟢' if r.get('online') else '🔴'} {r.get('name', r.get('id'))}" for r in results]
        text = (
            _txt("📡 Результаты пинга:\n", "📡 Ping results:\n") + "\n".join(lines)
            if lines
            else _txt("Нет узлов", "No nodes")
        )
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, reply_markup=kb_back("menu_federation"))


@router.callback_query(F.data.startswith("fed_ping_"))
async def cb_fed_ping(cq: CallbackQuery):
    nid = int(cq.data.split("_")[-1])
    await cq.answer(_txt("Пингую…", "Pinging…"))
    try:
        result = await federation_api.ping(nid)
        online = result.get("online", False)
        name = result.get("node", str(nid))
        text = f"{'🟢' if online else '🔴'} {name}: {_txt('онлайн', 'online') if online else _txt('офлайн', 'offline')}"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, reply_markup=kb_back("menu_federation"))


@router.callback_query(F.data.startswith("fed_delete_"))
async def cb_fed_delete(cq: CallbackQuery):
    nid = int(cq.data.split("_")[-1])
    try:
        await federation_api.delete(nid)
        await cq.answer(_txt("✅ Удалено", "✅ Deleted"))
        await cq.message.edit_text(_txt("✅ Узел удалён", "✅ Node deleted"), reply_markup=kb_back("menu_federation"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data == "federation_add")
async def cb_federation_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddNodeFSM.name)
    await cq.message.answer(_txt("Введите имя узла:", "Enter node name:"))
    await cq.answer()


@router.message(AddNodeFSM.name)
async def fsm_node_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    await state.set_state(AddNodeFSM.url)
    await msg.answer(_txt("Введите URL узла (например, https://node.example.com):", "Enter node URL (e.g. https://node.example.com):"))


@router.message(AddNodeFSM.url)
async def fsm_node_url(msg: Message, state: FSMContext):
    await state.update_data(url=msg.text.strip())
    await state.set_state(AddNodeFSM.secret)
    await msg.answer(
        _txt(
            "Введите секрет федерации удалённого узла:\n\n"
            "Подсказка: откройте Федерация -> Мой секрет на удалённом сервере.",
            "Enter the remote node federation secret:\n\n"
            "Tip: open Federation -> My secret on that remote server.",
        ),
    )


@router.message(AddNodeFSM.secret)
async def fsm_node_secret(msg: Message, state: FSMContext):
    await state.update_data(secret=msg.text.strip())
    await state.set_state(AddNodeFSM.role)
    from bot.keyboards.main import kb_node_role
    await msg.answer(_txt("Выберите роль узла:", "Select node role:"), reply_markup=kb_node_role())


@router.callback_query(AddNodeFSM.role, F.data.startswith("noderole_"))
async def fsm_node_role(cq: CallbackQuery, state: FSMContext):
    role = cq.data.replace("noderole_", "")
    data = await state.get_data()
    await state.clear()
    try:
        node = await federation_api.add(data["name"], data["url"], data["secret"], role)
        online_str = "🟢 онлайн" if node.get("is_active") else "🔴 офлайн"
        if not _is_ru():
            online_str = "🟢 online" if node.get("is_active") else "🔴 offline"
        text = (
            _txt(
                f"✅ Узел <b>{data['name']}</b> добавлен\n"
                f"URL: {data['url']}\n"
                f"Роль: {role}\n"
                f"Статус: {online_str}",
                f"✅ Node <b>{data['name']}</b> added\n"
                f"URL: {data['url']}\n"
                f"Role: {role}\n"
                f"Status: {online_str}",
            )
        )
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_federation"))
    await cq.answer()


# ─── Create Bridge ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "federation_bridge")
async def cb_federation_bridge(cq: CallbackQuery, state: FSMContext):
    """Start bridge creation: show list of online nodes to select as chain."""
    try:
        nodes = await federation_api.list()
        active = [n for n in nodes if n.get("is_active")]
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return

    if not active:
        await cq.answer(_txt("❌ Нет онлайн-узлов", "❌ No online nodes available"), show_alert=True)
        return

    await state.set_state(CreateBridgeFSM.selecting)
    await state.update_data(selected_ids=[], nodes=nodes)
    await cq.message.edit_text(
        _txt(
            "🌉 <b>Создание Bridge</b>\n\n"
            "Выберите узлы в порядке цепочки (1 → 2 → ... → Internet).\n"
            "Один узел = прямой выход. Несколько = multi-hop.\n\n"
            "<i>Показаны только онлайн-узлы.</i>",
            "🌉 <b>Create Bridge</b>\n\n"
            "Select nodes in chain order (1 → 2 → ... → Internet).\n"
            "Single node = direct exit. Multiple = multi-hop.\n\n"
            "<i>Only online nodes are shown.</i>",
        ),
        reply_markup=kb_bridge_node_select(active, []),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(CreateBridgeFSM.selecting, F.data.startswith("bridge_pick_"))
async def cb_bridge_pick(cq: CallbackQuery, state: FSMContext):
    nid = int(cq.data.replace("bridge_pick_", ""))
    data = await state.get_data()
    selected: list = data.get("selected_ids", [])
    nodes: list = data.get("nodes", [])

    if nid in selected:
        selected.remove(nid)   # deselect
    else:
        selected.append(nid)   # add to chain

    await state.update_data(selected_ids=selected)
    active = [n for n in nodes if n.get("is_active")]

    # Build chain preview
    names = []
    for i in selected:
        n = next((n for n in nodes if n["id"] == i), None)
        if n:
            names.append(n["name"])
    chain_str = " → ".join([_txt("(этот сервер)", "(this server)")] + names + ["Internet"]) if names else _txt("нет", "none")

    await cq.message.edit_text(
        _txt(
            f"🌉 <b>Создание Bridge</b>\n\n"
            f"Цепочка: <code>{chain_str}</code>\n\n"
            "Выберите узлы в порядке цепочки:",
            f"🌉 <b>Create Bridge</b>\n\n"
            f"Chain: <code>{chain_str}</code>\n\n"
            "Select nodes in chain order:",
        ),
        reply_markup=kb_bridge_node_select(active, selected),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(CreateBridgeFSM.selecting, F.data == "bridge_confirm")
async def cb_bridge_confirm(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected: list = data.get("selected_ids", [])
    await state.clear()

    if not selected:
        await cq.answer(_txt("❌ Не выбраны узлы", "❌ No nodes selected"), show_alert=True)
        return

    await cq.answer(_txt("⏳ Создаю bridge…", "⏳ Creating bridge…"))
    await cq.message.edit_text(
        _txt(
            "⏳ <b>Создаю bridge...</b>\n\nНастраиваю клиентов на удалённых узлах...",
            "⏳ <b>Creating bridge...</b>\n\nProvisioning clients on remote nodes...",
        ),
        parse_mode="HTML",
    )

    try:
        result = await federation_api.create_bridge(selected)
        chain = result.get("chain", "?")
        entry_outbound = result.get("entry_outbound", "")
        outbounds = result.get("outbounds", [])
        ob_lines = "\n".join(f"  • <code>{o['outbound_tag']}</code> on {o['server']}" for o in outbounds)
        text = (
            _txt(
                f"✅ <b>Bridge создан!</b>\n\n"
                f"Цепочка: <code>{chain}</code>\n\n"
                f"Маршрутизируйте трафик через: <code>{entry_outbound or '(неизвестно)'}</code>\n\n"
                f"Добавленные outbounds:\n{ob_lines or '  (нет)'}\n\n"
                f"Используйте <code>{entry_outbound or '(неизвестно)'}</code> в <b>Routing → Add rule</b>.",
                f"✅ <b>Bridge created!</b>\n\n"
                f"Chain: <code>{chain}</code>\n\n"
                f"Route traffic via: <code>{entry_outbound or '(unknown)'}</code>\n\n"
                f"Outbounds added:\n{ob_lines or '  (none)'}\n\n"
                f"Use <code>{entry_outbound or '(unknown)'}</code> in <b>Routing → Add rule</b>.",
            )
        )
    except APIError as e:
        text = _txt(f"❌ <b>Ошибка создания Bridge</b>\n\n{e.detail}", f"❌ <b>Bridge creation failed</b>\n\n{e.detail}")

    await cq.message.edit_text(text, reply_markup=kb_back("menu_federation"), parse_mode="HTML")
