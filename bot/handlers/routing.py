"""
Routing rules management.
Reads/writes Sing-Box route config via s-ui API.
Rule structure stored in bot's local DB for quick access;
synced to Sing-Box config on each change.
"""
import json
from typing import Optional, List

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, Document
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services.sui_api import sui, SuiAPIError
from bot.keyboards.main import back_kb, paginate_kb
from bot.texts import t
from bot.utils import paginate
from bot.middleware.auth import log_action

router = Router()

ITEMS_PER_PAGE = 10

RULE_TYPES = [
    ("routing_domains", "domain"),
    ("routing_ips", "ip_cidr"),
    ("routing_geosite", "geosite"),
    ("routing_geoip", "geoip"),
    ("routing_rulesets", "rule_set"),
]

ACTIONS = ["direct", "proxy", "block", "dns"]


class AddRuleFSM(StatesGroup):
    waiting_value = State()
    waiting_action = State()


# ─── Helpers ───────────────────────────────────────────────────────────────────

async def _get_route_config() -> dict:
    """Fetch sing-box config and return route section."""
    config = await sui.get_config()
    if isinstance(config, str):
        config = json.loads(config)
    return config


async def _save_route_config(config: dict) -> None:
    """Save updated config via s-ui API."""
    await sui._post("save", {"object": "config", "action": "save", "data": config})
    await sui.restart_singbox()


def _find_or_create_rule(rules: list, outbound: str, rule_key: str) -> dict:
    for rule in rules:
        if rule.get("outbound") == outbound and rule_key in rule:
            return rule
    new_rule = {"outbound": outbound, rule_key: []}
    rules.append(new_rule)
    return new_rule


def _collect_rule_values(rules: list, rule_key: str) -> list:
    """Collect all values of a rule_key across all rules as (value, outbound) pairs."""
    result = []
    for rule in rules:
        if rule_key in rule:
            outbound = rule.get("outbound", "direct")
            for v in rule[rule_key]:
                result.append((v, outbound))
    return result


# ─── Menu ──────────────────────────────────────────────────────────────────────

def routing_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("routing_domains"), callback_data="routing:list:domain:1"),
        InlineKeyboardButton(text=t("routing_ips"), callback_data="routing:list:ip_cidr:1"),
    )
    builder.row(
        InlineKeyboardButton(text=t("routing_geosite"), callback_data="routing:list:geosite:1"),
        InlineKeyboardButton(text=t("routing_geoip"), callback_data="routing:list:geoip:1"),
    )
    builder.row(
        InlineKeyboardButton(text=t("routing_rulesets"), callback_data="routing:list:rule_set:1"),
    )
    builder.row(
        InlineKeyboardButton(text=t("export"), callback_data="routing:export"),
        InlineKeyboardButton(text=t("import_btn"), callback_data="routing:import"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:routing")
async def cb_routing_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(t("routing_menu"), reply_markup=routing_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ─── List rules ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("routing:list:"))
async def cb_routing_list(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    rule_key = parts[2]
    page = int(parts[3])

    try:
        config = await _get_route_config()
        route = config.get("route", {})
        rules = route.get("rules", [])
        pairs = _collect_rule_values(rules, rule_key)
    except SuiAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:routing"))
        return

    if not pairs:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="➕ Добавить",
            callback_data=f"routing:add:{rule_key}",
        ))
        builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:routing"))
        await callback.message.edit_text(
            f"🔀 <b>{rule_key}</b> — правила отсутствуют",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    page_data, page, total_pages = paginate(pairs, page, ITEMS_PER_PAGE)
    items = []
    for idx, (val, outbound) in enumerate(page_data):
        abs_idx = (page - 1) * ITEMS_PER_PAGE + idx
        action_icon = {"direct": "➡", "proxy": "🔒", "block": "🚫", "dns": "🔍"}.get(outbound, "?")
        items.append({
            "label": f"{action_icon} {val}",
            "callback_data": f"routing:delete_confirm:{rule_key}:{abs_idx}",
        })

    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(InlineKeyboardButton(text=item["label"], callback_data=item["callback_data"]))

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text=t("prev"), callback_data=f"routing:list:{rule_key}:{page-1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text=t("next"), callback_data=f"routing:list:{rule_key}:{page+1}"))
    if nav:
        builder.row(*nav)

    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data=f"routing:add:{rule_key}"),
        InlineKeyboardButton(text=t("back"), callback_data="menu:routing"),
    )

    await callback.message.edit_text(
        f"🔀 <b>{rule_key}</b> [{len(pairs)}] • Стр. {page}/{total_pages}\n"
        f"<i>Нажмите на правило чтобы удалить</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── Delete rule ───────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("routing:delete_confirm:"))
async def cb_routing_delete_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    rule_key = parts[2]
    idx = int(parts[3])

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"routing:delete:{rule_key}:{idx}"),
        InlineKeyboardButton(text=t("cancel"), callback_data=f"routing:list:{rule_key}:1"),
    )
    await callback.message.edit_text(
        f"❓ Удалить правило #{idx} из <b>{rule_key}</b>?",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("routing:delete:"))
async def cb_routing_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    rule_key = parts[2]
    idx = int(parts[3])

    try:
        config = await _get_route_config()
        route = config.setdefault("route", {})
        rules = route.setdefault("rules", [])
        pairs = _collect_rule_values(rules, rule_key)

        if idx >= len(pairs):
            await callback.message.edit_text(t("error", msg="Index out of range"), reply_markup=back_kb("menu:routing"))
            return

        value_to_remove, outbound_to_remove = pairs[idx]
        for rule in rules:
            if rule.get("outbound") == outbound_to_remove and rule_key in rule:
                if value_to_remove in rule[rule_key]:
                    rule[rule_key].remove(value_to_remove)
                    if not rule[rule_key]:
                        rules.remove(rule)
                    break

        await _save_route_config(config)
        await log_action(callback.from_user.id, "delete_routing_rule", f"key={rule_key} val={value_to_remove}")
        await callback.message.edit_text(t("rule_deleted"), reply_markup=back_kb(f"routing:list:{rule_key}:1"))
    except SuiAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:routing"))


# ─── Add rule FSM ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("routing:add:"))
async def cb_routing_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    rule_key = callback.data.split(":")[2]
    await state.update_data(rule_key=rule_key)
    await state.set_state(AddRuleFSM.waiting_value)

    prompt_map = {
        "domain": t("ask_domain"),
        "ip_cidr": t("ask_ip"),
        "geosite": t("ask_geosite"),
        "geoip": t("ask_geoip"),
        "rule_set": t("ask_ruleset_url"),
    }
    await callback.message.answer(
        prompt_map.get(rule_key, "Введите значение:"),
        reply_markup=back_kb("menu:routing"),
    )


@router.message(AddRuleFSM.waiting_value)
async def fsm_rule_value(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    await state.update_data(value=value)
    await state.set_state(AddRuleFSM.waiting_action)

    builder = InlineKeyboardBuilder()
    for action in ACTIONS:
        icons = {"direct": "➡", "proxy": "🔒", "block": "🚫", "dns": "🔍"}
        builder.row(InlineKeyboardButton(
            text=f"{icons.get(action, '')} {action.capitalize()}",
            callback_data=f"routing:action:{action}",
        ))
    builder.row(InlineKeyboardButton(text=t("cancel"), callback_data="menu:routing"))
    await message.answer("Выберите действие для правила:", reply_markup=builder.as_markup())


@router.callback_query(AddRuleFSM.waiting_action, F.data.startswith("routing:action:"))
async def fsm_rule_action(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    action = callback.data.split(":")[2]
    data = await state.get_data()
    await state.clear()

    rule_key = data["rule_key"]
    value = data["value"]

    try:
        config = await _get_route_config()
        route = config.setdefault("route", {})
        rules = route.setdefault("rules", [])

        # For rule_set type, handle differently (URL-based)
        if rule_key == "rule_set":
            rule_sets = config.setdefault("route", {}).get("rule_set", [])
            tag = f"ruleset_{len(rule_sets)}"
            config["route"].setdefault("rule_set", []).append({
                "tag": tag,
                "type": "remote",
                "format": "binary" if value.endswith(".srs") else "source",
                "url": value,
                "download_detour": "direct",
            })
            target_rule = _find_or_create_rule(rules, action, "rule_set")
            target_rule["rule_set"].append(tag)
        else:
            target_rule = _find_or_create_rule(rules, action, rule_key)
            if value not in target_rule[rule_key]:
                target_rule[rule_key].append(value)

        await _save_route_config(config)
        await log_action(callback.from_user.id, "add_routing_rule", f"key={rule_key} val={value} action={action}")
        await callback.message.edit_text(
            t("rule_added") + f"\n\n<code>{rule_key}: {value}</code> → <b>{action}</b>",
            reply_markup=back_kb(f"routing:list:{rule_key}:1"),
            parse_mode="HTML",
        )
    except SuiAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:routing"))


# ─── Export / Import ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "routing:export")
async def cb_routing_export(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        config = await _get_route_config()
        route = config.get("route", {})
        export_data = {
            "rules": route.get("rules", []),
            "rule_set": route.get("rule_set", []),
        }
        content = json.dumps(export_data, indent=2, ensure_ascii=False)
        from aiogram.types import BufferedInputFile
        file = BufferedInputFile(content.encode(), filename="routing_rules.json")
        await callback.message.answer_document(file, caption="📤 Правила маршрутизации")
    except SuiAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


@router.callback_query(F.data == "routing:import")
async def cb_routing_import(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ImportRulesFSM.waiting_file)
    await callback.message.answer(
        "📥 Отправьте JSON файл с правилами маршрутизации.",
        reply_markup=back_kb("menu:routing"),
    )


class ImportRulesFSM(StatesGroup):
    waiting_file = State()


@router.message(ImportRulesFSM.waiting_file, F.document)
async def fsm_routing_import_file(message: Message, state: FSMContext) -> None:
    await state.clear()
    doc: Document = message.document
    if not doc.file_name.endswith(".json"):
        await message.answer("Отправьте файл с расширением .json")
        return
    try:
        from aiogram import Bot
        bot: Bot = message.bot
        file = await bot.get_file(doc.file_id)
        import io
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)
        buf.seek(0)
        import_data = json.loads(buf.read())

        config = await _get_route_config()
        route = config.setdefault("route", {})

        if "rules" in import_data:
            existing = route.setdefault("rules", [])
            for rule in import_data["rules"]:
                existing.append(rule)
        if "rule_set" in import_data:
            existing_rs = route.setdefault("rule_set", [])
            existing_tags = {rs["tag"] for rs in existing_rs}
            for rs in import_data["rule_set"]:
                if rs.get("tag") not in existing_tags:
                    existing_rs.append(rs)

        await _save_route_config(config)
        await log_action(message.from_user.id, "import_routing_rules")
        await message.answer("✅ Правила импортированы и применены.", reply_markup=back_kb("menu:routing"))
    except Exception as e:
        await message.answer(t("error", msg=str(e)))
