"""Routing rules management вЂ” thin wrapper over /api/routing/"""
import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from api.routers.settings_router import get_runtime
from bot.api_client import routing_api, APIError
from bot.keyboards.main import kb_back, kb_routing_menu, kb_routing_rules_list

router = Router()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en

# Note: geosite/geoip are Xray concepts, not supported in sing-box.
# For geo-based filtering use "Rule Set (.srs URL)" pointing to a remote SRS file.
def _rule_keys() -> dict[str, str]:
    return {
        "domain": _txt("🌐 Домен (точный)", "🌐 Domain (exact)"),
        "domain_suffix": _txt("🔠 Суффикс домена", "🔠 Domain Suffix"),
        "domain_keyword": _txt("🔍 Ключевое слово домена", "🔍 Domain Keyword"),
        "ip_cidr": _txt("📌 IP CIDR", "📌 IP CIDR"),
        "rule_set": _txt("📦 SRS Rule Set (URL)", "📦 SRS Rule Set (URL)"),
    }


class AddRuleFSM(StatesGroup):
    rule_key = State()
    value = State()
    outbound = State()
    srs_interval = State()  # only for rule_set type
    srs_detour   = State()  # only for rule_set type


class ImportRulesFSM(StatesGroup):
    waiting_file = State()


@router.callback_query(F.data == "menu_routing")
async def cb_routing_menu(cq: CallbackQuery):
    await cq.message.edit_text(
        _txt("рџ—є <b>РџСЂР°РІРёР»Р° РјР°СЂС€СЂСѓС‚РёР·Р°С†РёРё</b>", "рџ—є <b>Routing Rules</b>"),
        reply_markup=kb_routing_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("routing_view_"))
async def cb_routing_view(cq: CallbackQuery):
    rule_key = cq.data.replace("routing_view_", "")
    try:
        rules = await routing_api.list_rules(rule_key)
        if not rules:
            text = _txt(f"рџ“‹ РќРµС‚ РїСЂР°РІРёР» С‚РёРїР° <b>{rule_key}</b>", f"рџ“‹ No <b>{rule_key}</b> rules")
        else:
            lines = [f"вЂў {r['value']} в†’ {r['outbound']}" for r in rules]
            text = f"рџ“‹ <b>{_rule_keys().get(rule_key, rule_key)}</b>:\n" + "\n".join(lines)
    except APIError as e:
        text = f"вќЊ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_routing"))


@router.callback_query(F.data == "routing_add")
async def cb_routing_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddRuleFSM.rule_key)
    from bot.keyboards.main import kb_rule_key_select
    await cq.message.answer(_txt("Р’С‹Р±РµСЂРёС‚Рµ С‚РёРї РїСЂР°РІРёР»Р°:", "Select rule type:"), reply_markup=kb_rule_key_select(_rule_keys()))
    await cq.answer()


_RULE_HINTS = {
    "domain": (
        "Р’РІРµРґРёС‚Рµ С‚РѕС‡РЅС‹Рµ РґРѕРјРµРЅС‹.\nР§РµСЂРµР· Р·Р°РїСЏС‚СѓСЋ:\n<code>youtube.com, youtu.be, ytimg.com</code>",
        "Enter exact domain(s).\nComma-separated:\n<code>youtube.com, youtu.be, ytimg.com</code>",
    ),
    "domain_suffix": (
        "Р’РІРµРґРёС‚Рµ СЃСѓС„С„РёРєСЃС‹ РґРѕРјРµРЅРѕРІ вЂ” Р±СѓРґРµС‚ СЃРѕРІРїР°РґРµРЅРёРµ РґР»СЏ РґРѕРјРµРЅР° Рё РІСЃРµС… РїРѕРґРґРѕРјРµРЅРѕРІ.\nР§РµСЂРµР· Р·Р°РїСЏС‚СѓСЋ:\n<code>youtube.com, googlevideo.com</code>\n<i>(.youtube.com, www.youtube.com Рё С‚.Рґ. СѓС‡РёС‚С‹РІР°СЋС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё)</i>",
        "Enter domain suffix/suffixes вЂ” matches domain and all subdomains.\nComma-separated:\n<code>youtube.com, googlevideo.com</code>\n<i>(.youtube.com, www.youtube.com etc. are matched automatically)</i>",
    ),
    "domain_keyword": (
        "Р’РІРµРґРёС‚Рµ РєР»СЋС‡РµРІС‹Рµ СЃР»РѕРІР° вЂ” СЃРѕРІРїР°РґРµРЅРёРµ СЃ Р»СЋР±С‹Рј РґРѕРјРµРЅРѕРј, РєРѕС‚РѕСЂС‹Р№ СЃРѕРґРµСЂР¶РёС‚ СЃР»РѕРІРѕ.\nР§РµСЂРµР· Р·Р°РїСЏС‚СѓСЋ:\n<code>youtube, google, twitch</code>",
        "Enter keyword(s) вЂ” matches any domain containing the word.\nComma-separated:\n<code>youtube, google, twitch</code>",
    ),
    "ip_cidr": (
        "Р’РІРµРґРёС‚Рµ IP РёР»Рё CIDR-РґРёР°РїР°Р·РѕРЅС‹.\nР§РµСЂРµР· Р·Р°РїСЏС‚СѓСЋ:\n<code>8.8.8.8/32, 142.250.0.0/15</code>",
        "Enter IP or CIDR range(s).\nComma-separated:\n<code>8.8.8.8/32, 142.250.0.0/15</code>",
    ),
    "rule_set": (
        "Р’РІРµРґРёС‚Рµ URL SRS rule set С„Р°Р№Р»Р° (.srs binary РёР»Рё .json source).\nРџСЂРёРјРµСЂС‹:\n<code>https://github.com/SagerNet/sing-geosite/releases/download/20250101/geosite-youtube.srs</code>\n<code>https://github.com/legiz-ru/sb-rule-sets/raw/main/ru-bundle.srs</code>",
        "Enter URL of an SRS rule set file (.srs binary or .json source).\nExamples:\n<code>https://github.com/SagerNet/sing-geosite/releases/download/20250101/geosite-youtube.srs</code>\n<code>https://github.com/legiz-ru/sb-rule-sets/raw/main/ru-bundle.srs</code>",
    ),
}


@router.callback_query(AddRuleFSM.rule_key, F.data.startswith("rulekey_"))
async def fsm_rule_key(cq: CallbackQuery, state: FSMContext):
    rule_key = cq.data.replace("rulekey_", "")
    await state.update_data(rule_key=rule_key)
    await state.set_state(AddRuleFSM.value)
    hint_pair = _RULE_HINTS.get(rule_key)
    hint = _txt(*hint_pair) if hint_pair else _txt(
        f"Р’РІРµРґРёС‚Рµ Р·РЅР°С‡РµРЅРёРµ РґР»СЏ <b>{rule_key}</b>:",
        f"Enter value for <b>{rule_key}</b>:",
    )
    await cq.message.answer(hint, parse_mode="HTML")
    await cq.answer()


@router.message(AddRuleFSM.value)
async def fsm_rule_value(msg: Message, state: FSMContext):
    await state.update_data(value=msg.text.strip())
    await state.set_state(AddRuleFSM.outbound)
    try:
        data = await routing_api.get_outbounds()
        outbounds = data.get("outbounds", ["direct", "block"])
    except APIError:
        outbounds = ["proxy", "direct", "block", "dns"]
    from bot.keyboards.main import kb_outbound_select
    # Build hint about federation nodes
    node_tags = [o for o in outbounds if o not in ("proxy", "direct", "block", "dns")]
    hint = ""
    if node_tags:
        hint = _txt(
            f"\n\nрџ“Ў <i>Р”РѕСЃС‚СѓРїРЅС‹ СѓР·Р»С‹ С„РµРґРµСЂР°С†РёРё: {', '.join(node_tags)}</i>",
            f"\n\nрџ“Ў <i>Federation nodes available: {', '.join(node_tags)}</i>",
        )
    await msg.answer(
        _txt(f"Р’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ/outbound:{hint}", f"Select action/outbound:{hint}"),
        reply_markup=kb_outbound_select(outbounds),
        parse_mode="HTML",
    )


@router.callback_query(AddRuleFSM.outbound, F.data.startswith("outbound_"))
async def fsm_rule_outbound(cq: CallbackQuery, state: FSMContext):
    outbound = cq.data.replace("outbound_", "")
    await state.update_data(outbound=outbound)
    data = await state.get_data()

    # For rule_set, ask update_interval and download_detour
    if data.get("rule_key") == "rule_set":
        await state.set_state(AddRuleFSM.srs_interval)
        from bot.keyboards.main import kb_srs_interval
        await cq.message.answer(
            _txt("вЏ± РљР°Рє С‡Р°СЃС‚Рѕ Sing-Box РґРѕР»Р¶РµРЅ РѕР±РЅРѕРІР»СЏС‚СЊ СЌС‚РѕС‚ rule set?", "вЏ± How often should Sing-Box update this rule set?"),
            reply_markup=kb_srs_interval(),
        )
        await cq.answer()
        return

    await state.clear()
    try:
        await routing_api.add_rule(data["rule_key"], data["value"], outbound)
        await cq.message.answer(
            _txt(
                f"вњ… РџСЂР°РІРёР»Рѕ РґРѕР±Р°РІР»РµРЅРѕ: <b>{data['rule_key']}</b> = <code>{data['value']}</code> в†’ {outbound}",
                f"вњ… Rule added: <b>{data['rule_key']}</b> = <code>{data['value']}</code> в†’ {outbound}",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("menu_routing"),
        )
    except APIError as e:
        await cq.message.answer(f"вќЊ {e.detail}", reply_markup=kb_back("menu_routing"))
    await cq.answer()


@router.callback_query(AddRuleFSM.srs_interval, F.data.startswith("srsiv_"))
async def fsm_srs_interval(cq: CallbackQuery, state: FSMContext):
    interval = cq.data.replace("srsiv_", "")
    await state.update_data(srs_interval=interval)
    await state.set_state(AddRuleFSM.srs_detour)
    from bot.keyboards.main import kb_srs_detour
    await cq.message.answer(
        _txt(
            "рџ“Ґ РљР°Рє Sing-Box РґРѕР»Р¶РµРЅ СЃРєР°С‡РёРІР°С‚СЊ СЌС‚РѕС‚ rule set?\n\n"
            "вЂў <b>Direct</b> вЂ” РЅР°РїСЂСЏРјСѓСЋ РёР· РёРЅС‚РµСЂРЅРµС‚Р° (Р±С‹СЃС‚СЂРµРµ, РµСЃР»Рё GitHub РґРѕСЃС‚СѓРїРµРЅ)\n"
            "вЂў <b>Proxy</b> вЂ” С‡РµСЂРµР· РїСЂРѕРєСЃРё (РµСЃР»Рё GitHub/CDN Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅ РЅР° СЃРµСЂРІРµСЂРµ)",
            "рџ“Ґ How should Sing-Box download this rule set?\n\n"
            "вЂў <b>Direct</b> вЂ” download straight from the internet (fast, use if GitHub is reachable)\n"
            "вЂў <b>Proxy</b> вЂ” download through the proxy path (use if GitHub/CDN is blocked on your server)",
        ),
        reply_markup=kb_srs_detour(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(AddRuleFSM.srs_detour, F.data.startswith("srsdt_"))
async def fsm_srs_detour(cq: CallbackQuery, state: FSMContext):
    detour = cq.data.replace("srsdt_", "")
    data = await state.get_data()
    await state.clear()
    interval = data.get("srs_interval", "1d")
    outbound = data.get("outbound", "proxy")
    url = data.get("value", "")

    try:
        await routing_api.add_rule(
            "rule_set", url, outbound,
            download_detour=detour,
            update_interval=interval,
        )
        await cq.message.answer(
            _txt(
                f"вњ… SRS rule set РґРѕР±Р°РІР»РµРЅ:\n"
                f"URL: <code>{url}</code>\n"
                f"в†’ <b>{outbound}</b> | РѕР±РЅРѕРІР»РµРЅРёРµ: {interval} | Р·Р°РіСЂСѓР·РєР° С‡РµСЂРµР·: {detour}",
                f"вњ… SRS rule set added:\n"
                f"URL: <code>{url}</code>\n"
                f"в†’ <b>{outbound}</b> | update: {interval} | download via: {detour}",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("menu_routing"),
        )
    except APIError as e:
        await cq.message.answer(f"вќЊ {e.detail}", reply_markup=kb_back("menu_routing"))
    await cq.answer()


@router.callback_query(F.data == "routing_export")
async def cb_routing_export(cq: CallbackQuery):
    try:
        data = await routing_api.export()
        text = json.dumps(data, indent=2, ensure_ascii=False)
        file = BufferedInputFile(text.encode("utf-8"), filename="routing_rules.json")
        await cq.message.answer_document(
            file,
            caption=_txt("рџ—є Р­РєСЃРїРѕСЂС‚ РїСЂР°РІРёР» РјР°СЂС€СЂСѓС‚РёР·Р°С†РёРё", "рџ—є Routing rules export"),
        )
    except APIError as e:
        await cq.message.answer(f"вќЊ {e.detail}")
    await cq.answer()


@router.callback_query(F.data == "routing_import")
async def cb_routing_import(cq: CallbackQuery, state: FSMContext):
    await state.set_state(ImportRulesFSM.waiting_file)
    await cq.message.answer(
        _txt("рџ“Ћ РћС‚РїСЂР°РІСЊС‚Рµ JSON-С„Р°Р№Р» СЃ РїСЂР°РІРёР»Р°РјРё РјР°СЂС€СЂСѓС‚РёР·Р°С†РёРё РґР»СЏ РёРјРїРѕСЂС‚Р°:", "рџ“Ћ Send a JSON file with routing rules to import:")
    )
    await cq.answer()


@router.message(ImportRulesFSM.waiting_file, F.document)
async def fsm_import_file(msg: Message, state: FSMContext):
    await state.clear()
    doc = msg.document
    if not doc.file_name.endswith(".json"):
        await msg.answer(_txt("вќЊ РџРѕРґРґРµСЂР¶РёРІР°СЋС‚СЃСЏ С‚РѕР»СЊРєРѕ .json С„Р°Р№Р»С‹", "вќЊ Only .json files supported"))
        return
    file = await msg.bot.get_file(doc.file_id)
    content = await msg.bot.download_file(file.file_path)
    try:
        data = json.loads(content.read())
        result = await routing_api.import_rules(data)
        imported = result.get("detail", _txt("РРјРїРѕСЂС‚РёСЂРѕРІР°РЅРѕ", "Imported"))
        await msg.answer(f"вњ… {imported}", reply_markup=kb_back("menu_routing"))
    except (json.JSONDecodeError, APIError) as e:
        await msg.answer(f"вќЊ {e}", reply_markup=kb_back("menu_routing"))


