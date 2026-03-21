"""Routing rules management — thin wrapper over /api/routing/"""
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
        _txt("🗺 <b>Правила маршрутизации</b>", "🗺 <b>Routing Rules</b>"),
        reply_markup=kb_routing_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("routing_view_"))
async def cb_routing_view(cq: CallbackQuery):
    rule_key = cq.data.replace("routing_view_", "")
    try:
        rules = await routing_api.list_rules(rule_key)
        if not rules:
            text = _txt(f"📋 Нет правил типа <b>{rule_key}</b>", f"📋 No <b>{rule_key}</b> rules")
        else:
            lines = [f"• {r['value']} → {r['outbound']}" for r in rules]
            text = f"📋 <b>{_rule_keys().get(rule_key, rule_key)}</b>:\n" + "\n".join(lines)
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_routing"))


@router.callback_query(F.data == "routing_add")
async def cb_routing_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddRuleFSM.rule_key)
    from bot.keyboards.main import kb_rule_key_select
    await cq.message.answer(_txt("Выберите тип правила:", "Select rule type:"), reply_markup=kb_rule_key_select(_rule_keys()))
    await cq.answer()


_RULE_HINTS = {
    "domain": (
        "Введите точные домены.\nЧерез запятую:\n<code>youtube.com, youtu.be, ytimg.com</code>",
        "Enter exact domain(s).\nComma-separated:\n<code>youtube.com, youtu.be, ytimg.com</code>",
    ),
    "domain_suffix": (
        "Введите суффиксы доменов — будет совпадение для домена и всех поддоменов.\nЧерез запятую:\n<code>youtube.com, googlevideo.com</code>\n<i>(.youtube.com, www.youtube.com и т.д. учитываются автоматически)</i>",
        "Enter domain suffix/suffixes — matches domain and all subdomains.\nComma-separated:\n<code>youtube.com, googlevideo.com</code>\n<i>(.youtube.com, www.youtube.com etc. are matched automatically)</i>",
    ),
    "domain_keyword": (
        "Введите ключевые слова — совпадение с любым доменом, который содержит слово.\nЧерез запятую:\n<code>youtube, google, twitch</code>",
        "Enter keyword(s) — matches any domain containing the word.\nComma-separated:\n<code>youtube, google, twitch</code>",
    ),
    "ip_cidr": (
        "Введите IP или CIDR-диапазоны.\nЧерез запятую:\n<code>8.8.8.8/32, 142.250.0.0/15</code>",
        "Enter IP or CIDR range(s).\nComma-separated:\n<code>8.8.8.8/32, 142.250.0.0/15</code>",
    ),
    "rule_set": (
        "Введите URL SRS rule set файла (.srs binary или .json source).\nПримеры:\n<code>https://github.com/SagerNet/sing-geosite/releases/download/20250101/geosite-youtube.srs</code>\n<code>https://github.com/legiz-ru/sb-rule-sets/raw/main/ru-bundle.srs</code>",
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
        f"Введите значение для <b>{rule_key}</b>:",
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
        outbounds = ["proxy", "direct", "block", "warp", "dns"]
    from bot.keyboards.main import kb_outbound_select
    # Build hint about federation nodes
    node_tags = [o for o in outbounds if o not in ("proxy", "direct", "block", "warp", "dns")]
    hint = ""
    if node_tags:
        hint = _txt(
            f"\n\n📡 <i>Доступны узлы федерации: {', '.join(node_tags)}</i>",
            f"\n\n📡 <i>Federation nodes available: {', '.join(node_tags)}</i>",
        )
    await msg.answer(
        _txt(f"Выберите действие/outbound:{hint}", f"Select action/outbound:{hint}"),
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
            _txt("⏱ Как часто Sing-Box должен обновлять этот rule set?", "⏱ How often should Sing-Box update this rule set?"),
            reply_markup=kb_srs_interval(),
        )
        await cq.answer()
        return

    await state.clear()
    try:
        await routing_api.add_rule(data["rule_key"], data["value"], outbound)
        await cq.message.answer(
            _txt(
                f"✅ Правило добавлено: <b>{data['rule_key']}</b> = <code>{data['value']}</code> → {outbound}",
                f"✅ Rule added: <b>{data['rule_key']}</b> = <code>{data['value']}</code> → {outbound}",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("menu_routing"),
        )
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_routing"))
    await cq.answer()


@router.callback_query(AddRuleFSM.srs_interval, F.data.startswith("srsiv_"))
async def fsm_srs_interval(cq: CallbackQuery, state: FSMContext):
    interval = cq.data.replace("srsiv_", "")
    await state.update_data(srs_interval=interval)
    await state.set_state(AddRuleFSM.srs_detour)
    from bot.keyboards.main import kb_srs_detour
    await cq.message.answer(
        _txt(
            "📥 Как Sing-Box должен скачивать этот rule set?\n\n"
            "• <b>Direct</b> — напрямую из интернета (быстрее, если GitHub доступен)\n"
            "• <b>Proxy</b> — через прокси (если GitHub/CDN заблокирован на сервере)",
            "📥 How should Sing-Box download this rule set?\n\n"
            "• <b>Direct</b> — download straight from the internet (fast, use if GitHub is reachable)\n"
            "• <b>Proxy</b> — download through the proxy path (use if GitHub/CDN is blocked on your server)",
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
                f"✅ SRS rule set добавлен:\n"
                f"URL: <code>{url}</code>\n"
                f"→ <b>{outbound}</b> | обновление: {interval} | загрузка через: {detour}",
                f"✅ SRS rule set added:\n"
                f"URL: <code>{url}</code>\n"
                f"→ <b>{outbound}</b> | update: {interval} | download via: {detour}",
            ),
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
        await cq.message.answer_document(
            file,
            caption=_txt("🗺 Экспорт правил маршрутизации", "🗺 Routing rules export"),
        )
    except APIError as e:
        await cq.message.answer(f"❌ {e.detail}")
    await cq.answer()


@router.callback_query(F.data == "routing_import")
async def cb_routing_import(cq: CallbackQuery, state: FSMContext):
    await state.set_state(ImportRulesFSM.waiting_file)
    await cq.message.answer(
        _txt("📎 Отправьте JSON-файл с правилами маршрутизации для импорта:", "📎 Send a JSON file with routing rules to import:")
    )
    await cq.answer()


@router.message(ImportRulesFSM.waiting_file, F.document)
async def fsm_import_file(msg: Message, state: FSMContext):
    await state.clear()
    doc = msg.document
    if not doc.file_name.endswith(".json"):
        await msg.answer(_txt("❌ Поддерживаются только .json файлы", "❌ Only .json files supported"))
        return
    file = await msg.bot.get_file(doc.file_id)
    content = await msg.bot.download_file(file.file_path)
    try:
        data = json.loads(content.read())
        result = await routing_api.import_rules(data)
        imported = result.get("detail", _txt("Импортировано", "Imported"))
        await msg.answer(f"✅ {imported}", reply_markup=kb_back("menu_routing"))
    except (json.JSONDecodeError, APIError) as e:
        await msg.answer(f"❌ {e}", reply_markup=kb_back("menu_routing"))


