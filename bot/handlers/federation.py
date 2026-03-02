"""Federation — thin wrapper over /api/federation/"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.api_client import federation_api, APIError
from bot.keyboards.main import kb_back, kb_federation_menu, kb_nodes_list

router = Router()


class AddNodeFSM(StatesGroup):
    name = State()
    url = State()
    secret = State()
    role = State()


@router.callback_query(F.data == "menu_federation")
async def cb_federation_menu(cq: CallbackQuery):
    try:
        nodes = await federation_api.list()
        active = sum(1 for n in nodes if n.get("is_active"))
        text = f"🌐 <b>Federation</b> — nodes: {len(nodes)} ({active} online)"
        mk = kb_federation_menu(nodes)
    except APIError as e:
        text = f"❌ {e.detail}"
        mk = kb_back("main_menu")
    await cq.message.edit_text(text, reply_markup=mk, parse_mode="HTML")


@router.callback_query(F.data == "federation_topology")
async def cb_federation_topology(cq: CallbackQuery):
    try:
        topo = await federation_api.topology()
        master = topo.get("master", "this server")
        nodes = topo.get("nodes", [])
        lines = [f"🖥 <b>{master}</b> (master)"]
        for n in nodes:
            icon = "🟢" if n.get("is_active") else "🔴"
            lines.append(f"  └─ {icon} {n['name']} [{n['role']}] — {n['url']}")
        text = "\n".join(lines) or "No nodes"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_federation"))


@router.callback_query(F.data == "federation_ping_all")
async def cb_federation_ping_all(cq: CallbackQuery):
    await cq.answer("Pinging…")
    try:
        results = await federation_api.ping_all()
        lines = [f"{'🟢' if r.get('online') else '🔴'} {r.get('name', r.get('id'))}" for r in results]
        text = "📡 Ping results:\n" + "\n".join(lines) if lines else "No nodes"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, reply_markup=kb_back("menu_federation"))


@router.callback_query(F.data.startswith("fed_ping_"))
async def cb_fed_ping(cq: CallbackQuery):
    nid = int(cq.data.split("_")[-1])
    await cq.answer("Pinging…")
    try:
        result = await federation_api.ping(nid)
        online = result.get("online", False)
        name = result.get("node", str(nid))
        text = f"{'🟢' if online else '🔴'} {name}: {'online' if online else 'offline'}"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, reply_markup=kb_back("menu_federation"))


@router.callback_query(F.data.startswith("fed_delete_"))
async def cb_fed_delete(cq: CallbackQuery):
    nid = int(cq.data.split("_")[-1])
    try:
        await federation_api.delete(nid)
        await cq.answer("✅ Deleted")
        await cq.message.edit_text("✅ Node deleted", reply_markup=kb_back("menu_federation"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data == "federation_add")
async def cb_federation_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddNodeFSM.name)
    await cq.message.answer("Enter node name:")
    await cq.answer()


@router.message(AddNodeFSM.name)
async def fsm_node_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    await state.set_state(AddNodeFSM.url)
    await msg.answer("Enter node URL (e.g. https://node.example.com):")


@router.message(AddNodeFSM.url)
async def fsm_node_url(msg: Message, state: FSMContext):
    await state.update_data(url=msg.text.strip())
    await state.set_state(AddNodeFSM.secret)
    await msg.answer("Enter shared federation secret:")


@router.message(AddNodeFSM.secret)
async def fsm_node_secret(msg: Message, state: FSMContext):
    await state.update_data(secret=msg.text.strip())
    await state.set_state(AddNodeFSM.role)
    from bot.keyboards.main import kb_node_role
    await msg.answer("Select node role:", reply_markup=kb_node_role())


@router.callback_query(AddNodeFSM.role, F.data.startswith("noderole_"))
async def fsm_node_role(cq: CallbackQuery, state: FSMContext):
    role = cq.data.replace("noderole_", "")
    data = await state.get_data()
    await state.clear()
    try:
        node = await federation_api.add(data["name"], data["url"], data["secret"], role)
        online_str = "🟢 online" if node.get("is_active") else "🔴 offline"
        text = (
            f"✅ Node <b>{data['name']}</b> added\n"
            f"URL: {data['url']}\n"
            f"Role: {role}\n"
            f"Status: {online_str}"
        )
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_federation"))
    await cq.answer()
