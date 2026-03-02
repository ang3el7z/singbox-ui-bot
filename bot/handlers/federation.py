from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.database import async_session, FederationNode
from bot.services.federation_service import fed_client
from bot.keyboards.main import back_kb
from bot.texts import t
from bot.middleware.auth import log_action
from sqlalchemy import select, delete

router = Router()


class AddNodeFSM(StatesGroup):
    waiting_name = State()
    waiting_url = State()
    waiting_secret = State()


class BridgeFSM(StatesGroup):
    selecting_nodes = State()


# ─── Menu ──────────────────────────────────────────────────────────────────────

def federation_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("federation_nodes"), callback_data="fed:nodes"),
        InlineKeyboardButton(text=t("federation_add_node"), callback_data="fed:add_node"),
    )
    builder.row(
        InlineKeyboardButton(text=t("federation_bridge"), callback_data="fed:bridge_start"),
        InlineKeyboardButton(text=t("federation_topology"), callback_data="fed:topology"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:federation")
async def cb_fed_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(t("federation_menu"), reply_markup=federation_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ─── Node list ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "fed:nodes")
async def cb_fed_nodes(callback: CallbackQuery) -> None:
    await callback.answer()
    nodes = await fed_client.get_all_nodes()

    if not nodes:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text=t("federation_add_node"), callback_data="fed:add_node"))
        builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:federation"))
        await callback.message.edit_text(
            "🔗 <b>Ноды федерации</b>\n\n<i>Ноды не добавлены</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    builder = InlineKeyboardBuilder()
    for node in nodes:
        status = t("node_online") if node["is_active"] else t("node_offline")
        builder.row(InlineKeyboardButton(
            text=f"{status} {node['name']}",
            callback_data=f"fed:node_view:{node['id']}",
        ))
    builder.row(
        InlineKeyboardButton(text="🔄 Пинг всех", callback_data="fed:ping_all"),
        InlineKeyboardButton(text=t("federation_add_node"), callback_data="fed:add_node"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:federation"))
    await callback.message.edit_text(
        f"🔗 <b>Ноды федерации</b> [{len(nodes)}]",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "fed:ping_all")
async def cb_fed_ping_all(callback: CallbackQuery) -> None:
    await callback.answer("Пингую ноды...")
    results = await fed_client.ping_all_nodes()
    lines = ["🔄 <b>Результаты пинга:</b>\n"]
    for r in results:
        icon = "🟢" if r["online"] else "🔴"
        lines.append(f"{icon} <b>{r['name']}</b> — {r['url']}")
    await callback.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=back_kb("fed:nodes"))


# ─── View / delete single node ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fed:node_view:"))
async def cb_fed_node_view(callback: CallbackQuery) -> None:
    await callback.answer()
    node_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        node = await session.get(FederationNode, node_id)
    if not node:
        await callback.message.edit_text(t("error", msg="Node not found"), reply_markup=back_kb("fed:nodes"))
        return

    ping_ok = await fed_client.ping_node(node.url, node.secret)
    status = t("node_online") if ping_ok else t("node_offline")
    ping_str = node.last_ping.strftime("%Y-%m-%d %H:%M") if node.last_ping else "н/д"

    text = (
        f"🔗 <b>Нода: {node.name}</b>\n\n"
        f"▪ URL: <code>{node.url}</code>\n"
        f"▪ Роль: <code>{node.role}</code>\n"
        f"▪ Статус: {status}\n"
        f"▪ Последний пинг: {ping_str}"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Пинг", callback_data=f"fed:node_ping:{node_id}"),
        InlineKeyboardButton(text="📡 Inbounds", callback_data=f"fed:node_inbounds:{node_id}"),
    )
    builder.row(
        InlineKeyboardButton(text=t("delete"), callback_data=f"fed:node_delete_confirm:{node_id}"),
        InlineKeyboardButton(text=t("back"), callback_data="fed:nodes"),
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("fed:node_ping:"))
async def cb_fed_node_ping(callback: CallbackQuery) -> None:
    await callback.answer()
    node_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        node = await session.get(FederationNode, node_id)
    if not node:
        return
    ok = await fed_client.ping_node(node.url, node.secret)
    await callback.message.answer(
        f"{'🟢 Нода доступна' if ok else '🔴 Нода недоступна'}: <b>{node.name}</b>",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("fed:node_inbounds:"))
async def cb_fed_node_inbounds(callback: CallbackQuery) -> None:
    await callback.answer()
    node_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        node = await session.get(FederationNode, node_id)
    if not node:
        return
    try:
        inbounds = await fed_client.get_remote_inbounds(node.url, node.secret)
        lines = [f"📡 <b>Inbounds ноды {node.name}:</b>\n"]
        for ib in inbounds:
            lines.append(f"• [{ib.get('type', '?')}] {ib.get('tag', '?')} → {ib.get('host')}:{ib.get('port')}")
        text = "\n".join(lines) if len(lines) > 1 else "Нет доступных inbounds."
    except Exception as e:
        text = t("error", msg=str(e))
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("fed:node_delete_confirm:"))
async def cb_fed_node_delete_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    node_id = int(callback.data.split(":")[2])
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"fed:node_delete:{node_id}"),
        InlineKeyboardButton(text=t("cancel"), callback_data=f"fed:node_view:{node_id}"),
    )
    await callback.message.edit_text(
        f"❓ Удалить ноду #{node_id}?",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("fed:node_delete:"))
async def cb_fed_node_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    node_id = int(callback.data.split(":")[2])
    async with async_session() as session:
        node = await session.get(FederationNode, node_id)
        if node:
            await session.delete(node)
            await session.commit()
    await log_action(callback.from_user.id, "delete_fed_node", f"id={node_id}")
    await callback.message.edit_text(t("node_deleted"), reply_markup=back_kb("fed:nodes"))


# ─── Add node FSM ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "fed:add_node")
async def cb_fed_add_node(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AddNodeFSM.waiting_name)
    await callback.message.answer(t("ask_node_name"), reply_markup=back_kb("menu:federation"))


@router.message(AddNodeFSM.waiting_name)
async def fsm_node_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(AddNodeFSM.waiting_url)
    await message.answer(t("ask_node_url"), reply_markup=back_kb("menu:federation"))


@router.message(AddNodeFSM.waiting_url)
async def fsm_node_url(message: Message, state: FSMContext) -> None:
    url = message.text.strip().rstrip("/")
    if not url.startswith("http"):
        await message.answer("URL должен начинаться с http:// или https://")
        return
    await state.update_data(url=url)
    await state.set_state(AddNodeFSM.waiting_secret)
    await message.answer(t("ask_node_secret"), reply_markup=back_kb("menu:federation"))


@router.message(AddNodeFSM.waiting_secret)
async def fsm_node_secret(message: Message, state: FSMContext) -> None:
    secret = message.text.strip()
    data = await state.get_data()
    await state.clear()

    name = data["name"]
    url = data["url"]

    # Test connectivity before saving
    is_online = await fed_client.ping_node(url, secret)

    async with async_session() as session:
        node = FederationNode(name=name, url=url, secret=secret, is_active=is_online)
        session.add(node)
        await session.commit()

    await log_action(message.from_user.id, "add_fed_node", f"name={name} url={url}")
    status = t("node_online") if is_online else t("node_offline")
    await message.answer(
        t("node_added", name=name) + f"\n▪ Статус: {status}",
        reply_markup=back_kb("fed:nodes"),
        parse_mode="HTML",
    )


# ─── Bridge ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "fed:bridge_start")
async def cb_fed_bridge_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    nodes = await fed_client.get_all_nodes()
    if len(nodes) < 1:
        await callback.message.edit_text(
            "❌ Для создания bridge нужно минимум 1 удалённая нода.",
            reply_markup=back_kb("menu:federation"),
        )
        return

    await state.set_state(BridgeFSM.selecting_nodes)
    await state.update_data(selected_ids=[])

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🖥 (Текущий сервер — старт цепи)",
        callback_data="fed:bridge_local",
    ))
    for node in nodes:
        builder.row(InlineKeyboardButton(
            text=f"{'🟢' if node['is_active'] else '🔴'} {node['name']}",
            callback_data=f"fed:bridge_pick:{node['id']}",
        ))
    builder.row(
        InlineKeyboardButton(text="✅ Создать bridge", callback_data="fed:bridge_confirm"),
        InlineKeyboardButton(text=t("cancel"), callback_data="menu:federation"),
    )
    await callback.message.edit_text(
        t("select_nodes_for_bridge") + "\n\n<i>Нажимайте ноды в нужном порядке (ваш сервер всегда первый)</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(BridgeFSM.selecting_nodes, F.data.startswith("fed:bridge_pick:"))
async def cb_fed_bridge_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    node_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    selected = data.get("selected_ids", [])
    if node_id not in selected:
        selected.append(node_id)
        await state.update_data(selected_ids=selected)
        await callback.message.answer(f"✅ Нода #{node_id} добавлена в цепочку (позиция {len(selected)})")
    else:
        await callback.answer("Уже добавлена", show_alert=True)


@router.callback_query(BridgeFSM.selecting_nodes, F.data == "fed:bridge_confirm")
async def cb_fed_bridge_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    selected_ids = data.get("selected_ids", [])
    await state.clear()

    if not selected_ids:
        await callback.message.edit_text("❌ Не выбрано ни одной ноды.", reply_markup=back_kb("menu:federation"))
        return

    all_nodes = await fed_client.get_all_nodes()
    nodes_map = {n["id"]: n for n in all_nodes}

    chain = [nodes_map[nid] for nid in selected_ids if nid in nodes_map]
    if not chain:
        await callback.message.edit_text("❌ Ноды не найдены.", reply_markup=back_kb("menu:federation"))
        return

    await callback.message.edit_text("⏳ Настраиваю bridge цепочку...")
    try:
        await fed_client.create_bridge(chain)
        chain_str = " → ".join(["(этот сервер)"] + [n["name"] for n in chain] + ["Internet"])
        await log_action(callback.from_user.id, "create_bridge", chain_str)
        await callback.message.edit_text(
            t("bridge_created", chain=chain_str),
            reply_markup=back_kb("menu:federation"),
            parse_mode="HTML",
        )
    except Exception as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:federation"))


# ─── Topology ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "fed:topology")
async def cb_fed_topology(callback: CallbackQuery) -> None:
    await callback.answer()
    nodes = await fed_client.get_all_nodes()
    from bot.config import settings

    lines = ["🗺 <b>Топология сети</b>\n"]
    lines.append(f"🖥 <b>{settings.domain or 'Текущий сервер'}</b> (мастер)")

    for node in nodes:
        status_icon = "🟢" if node["is_active"] else "🔴"
        ping_str = node["last_ping"].strftime("%H:%M") if node.get("last_ping") else "н/д"
        lines.append(f"  └─ {status_icon} <b>{node['name']}</b> [{node['role']}] | пинг: {ping_str}")
        lines.append(f"       <code>{node['url']}</code>")

    if len(nodes) == 0:
        lines.append("\n<i>Нодов нет. Добавьте первую ноду.</i>")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_kb("menu:federation"),
        parse_mode="HTML",
    )
