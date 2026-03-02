"""Routing rules management — thin wrapper over /api/routing/"""
import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.api_client import routing_api, APIError
from bot.keyboards.main import kb_back, kb_routing_menu, kb_routing_rules_list

router = Router()

RULE_KEYS = {
    "domain": "Domain",
    "domain_suffix": "Domain Suffix",
    "domain_keyword": "Keyword",
    "ip_cidr": "IP CIDR",
    "geosite": "GeoSite",
    "geoip": "GeoIP",
    "rule_set": "Rule Set URL",
}


class AddRuleFSM(StatesGroup):
    rule_key = State()
    value = State()
    outbound = State()


class ImportRulesFSM(StatesGroup):
    waiting_file = State()


@router.callback_query(F.data == "menu_routing")
async def cb_routing_menu(cq: CallbackQuery):
    await cq.message.edit_text("🗺 <b>Routing Rules</b>", reply_markup=kb_routing_menu(), parse_mode="HTML")


@router.callback_query(F.data.startswith("routing_view_"))
async def cb_routing_view(cq: CallbackQuery):
    rule_key = cq.data.replace("routing_view_", "")
    try:
        rules = await routing_api.list_rules(rule_key)
        if not rules:
            text = f"📋 No <b>{rule_key}</b> rules"
        else:
            lines = [f"• {r['value']} → {r['outbound']}" for r in rules]
            text = f"📋 <b>{RULE_KEYS.get(rule_key, rule_key)}</b>:\n" + "\n".join(lines)
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_routing"))


@router.callback_query(F.data == "routing_add")
async def cb_routing_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddRuleFSM.rule_key)
    from bot.keyboards.main import kb_rule_key_select
    await cq.message.answer("Select rule type:", reply_markup=kb_rule_key_select(RULE_KEYS))
    await cq.answer()


@router.callback_query(AddRuleFSM.rule_key, F.data.startswith("rulekey_"))
async def fsm_rule_key(cq: CallbackQuery, state: FSMContext):
    rule_key = cq.data.replace("rulekey_", "")
    await state.update_data(rule_key=rule_key)
    await state.set_state(AddRuleFSM.value)
    label = RULE_KEYS.get(rule_key, rule_key)
    await cq.message.answer(f"Enter {label} value:")
    await cq.answer()


@router.message(AddRuleFSM.value)
async def fsm_rule_value(msg: Message, state: FSMContext):
    await state.update_data(value=msg.text.strip())
    await state.set_state(AddRuleFSM.outbound)
    from bot.keyboards.main import kb_outbound_select
    await msg.answer("Select action/outbound:", reply_markup=kb_outbound_select())


@router.callback_query(AddRuleFSM.outbound, F.data.startswith("outbound_"))
async def fsm_rule_outbound(cq: CallbackQuery, state: FSMContext):
    outbound = cq.data.replace("outbound_", "")
    data = await state.get_data()
    await state.clear()
    try:
        await routing_api.add_rule(data["rule_key"], data["value"], outbound)
        await cq.message.answer(
            f"✅ Rule added: <b>{data['rule_key']}</b> = <code>{data['value']}</code> → {outbound}",
            parse_mode="HTML",
            reply_markup=kb_back("menu_routing"),
        )
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_routing"))
    await cq.answer()


@router.callback_query(F.data == "routing_export")
async def cb_routing_export(cq: CallbackQuery):
    try:
        data = await routing_api.export()
        text = json.dumps(data, indent=2, ensure_ascii=False)
        file = BufferedInputFile(text.encode("utf-8"), filename="routing_rules.json")
        await cq.message.answer_document(file, caption="🗺 Routing rules export")
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}")
    await cq.answer()


@router.callback_query(F.data == "routing_import")
async def cb_routing_import(cq: CallbackQuery, state: FSMContext):
    await state.set_state(ImportRulesFSM.waiting_file)
    await cq.message.answer("📎 Send a JSON file with routing rules to import:")
    await cq.answer()


@router.message(ImportRulesFSM.waiting_file, F.document)
async def fsm_import_file(msg: Message, state: FSMContext):
    await state.clear()
    doc = msg.document
    if not doc.file_name.endswith(".json"):
        await msg.answer("❌ Only .json files supported")
        return
    file = await msg.bot.get_file(doc.file_id)
    content = await msg.bot.download_file(file.file_path)
    try:
        data = json.loads(content.read())
        result = await routing_api.import_rules(data)
        await msg.answer(f"✅ {result.get('detail', 'Imported')}", reply_markup=kb_back("menu_routing"))
    except (json.JSONDecodeError, APIError) as e:
        await msg.answer(f"❌ {e}", reply_markup=kb_back("menu_routing"))
