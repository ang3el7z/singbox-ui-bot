from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services.adguard_api import adguard, AdGuardAPIError
from bot.services.sui_api import sui, SuiAPIError
from bot.keyboards.main import back_kb, paginate_kb
from bot.texts import t
from bot.utils import paginate
from bot.middleware.auth import log_action

router = Router()

ITEMS_PER_PAGE = 10


class AdGuardFSM(StatesGroup):
    waiting_upstream = State()
    waiting_filter_rule = State()
    waiting_password = State()


# ─── Menu ──────────────────────────────────────────────────────────────────────

def adguard_menu_kb(protection_enabled: bool = True) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("adguard_stats"), callback_data="adguard:stats"),
        InlineKeyboardButton(
            text="⛔ Выкл. защиту" if protection_enabled else "✅ Вкл. защиту",
            callback_data=f"adguard:protection:{'off' if protection_enabled else 'on'}",
        ),
    )
    builder.row(
        InlineKeyboardButton(text=t("adguard_upstream"), callback_data="adguard:upstream:list"),
        InlineKeyboardButton(text=t("adguard_rules"), callback_data="adguard:rules:1"),
    )
    builder.row(
        InlineKeyboardButton(text=t("adguard_password"), callback_data="adguard:password"),
        InlineKeyboardButton(text=t("adguard_sync"), callback_data="adguard:sync"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:adguard")
async def cb_adguard_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        status = await adguard.get_status()
        protection_on = status.get("protection_enabled", True)
        header = t("adguard_status_on") if protection_on else t("adguard_status_off")
        dns_status = status.get("dns_addresses", [])
        version = status.get("version", "?")
        text = (
            f"🛡 <b>AdGuard Home</b>\n\n"
            f"▪ Статус: {header}\n"
            f"▪ Версия: {version}\n"
            f"▪ DNS: {', '.join(dns_status) if dns_status else 'н/д'}"
        )
    except AdGuardAPIError:
        protection_on = True
        text = f"🛡 <b>AdGuard Home</b>\n\n{t('adguard_status_off')}"

    await callback.message.edit_text(
        text,
        reply_markup=adguard_menu_kb(protection_on),
        parse_mode="HTML",
    )


# ─── Protection toggle ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adguard:protection:"))
async def cb_adguard_protection(callback: CallbackQuery) -> None:
    await callback.answer()
    state_str = callback.data.split(":")[2]
    enabled = state_str == "on"
    try:
        await adguard.enable_protection(enabled)
        await log_action(callback.from_user.id, "adguard_protection", f"enabled={enabled}")
        await callback.message.answer(
            "✅ Защита включена" if enabled else "⛔ Защита выключена"
        )
        # Refresh menu
        status = await adguard.get_status()
        protection_on = status.get("protection_enabled", True)
        await callback.message.edit_text(
            t("adguard_menu"),
            reply_markup=adguard_menu_kb(protection_on),
            parse_mode="HTML",
        )
    except AdGuardAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Stats ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adguard:stats")
async def cb_adguard_stats(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        stats = await adguard.get_stats()
        total = stats.get("num_dns_queries", 0)
        blocked = stats.get("num_blocked_filtering", 0)
        blocked_pct = round(blocked / total * 100, 1) if total > 0 else 0
        safe_searches = stats.get("num_replaced_safesearch", 0)
        avg_time = stats.get("avg_processing_time", 0)

        top_queries = stats.get("top_queried_domains", [])[:5]
        top_blocked = stats.get("top_blocked_domains", [])[:5]

        text = (
            f"📊 <b>Статистика AdGuard Home</b>\n\n"
            f"▪ DNS запросов: <b>{total:,}</b>\n"
            f"▪ Заблокировано: <b>{blocked:,}</b> ({blocked_pct}%)\n"
            f"▪ Безопасный поиск: <b>{safe_searches:,}</b>\n"
            f"▪ Среднее время: <b>{avg_time:.1f}ms</b>\n\n"
        )
        if top_queries:
            text += "🔝 <b>Топ запросов:</b>\n"
            for item in top_queries:
                if isinstance(item, dict):
                    for domain, count in item.items():
                        text += f"  • {domain}: {count}\n"
        if top_blocked:
            text += "\n🚫 <b>Топ заблокированных:</b>\n"
            for item in top_blocked:
                if isinstance(item, dict):
                    for domain, count in item.items():
                        text += f"  • {domain}: {count}\n"
    except AdGuardAPIError as e:
        text = t("error", msg=str(e))

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("refresh"), callback_data="adguard:stats"),
        InlineKeyboardButton(text=t("back"), callback_data="menu:adguard"),
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ─── Upstream DNS ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adguard:upstream:list")
async def cb_adguard_upstream_list(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        dns_info = await adguard.get_dns_info()
        upstreams = dns_info.get("upstream_dns", [])
    except AdGuardAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:adguard"))
        return

    text = "🔗 <b>Upstream DNS серверы:</b>\n\n"
    if upstreams:
        for i, u in enumerate(upstreams):
            text += f"  {i+1}. <code>{u}</code>\n"
    else:
        text += "<i>Не настроены</i>"

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="adguard:upstream:add"),
    )
    for i, u in enumerate(upstreams):
        builder.row(InlineKeyboardButton(
            text=f"🗑 {u}",
            callback_data=f"adguard:upstream:del:{i}",
        ))
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:adguard"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "adguard:upstream:add")
async def cb_adguard_upstream_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdGuardFSM.waiting_upstream)
    await callback.message.answer(t("ask_upstream"), reply_markup=back_kb("adguard:upstream:list"))


@router.message(AdGuardFSM.waiting_upstream)
async def fsm_adguard_upstream(message: Message, state: FSMContext) -> None:
    await state.clear()
    upstream = message.text.strip()
    try:
        dns_info = await adguard.get_dns_info()
        upstreams = dns_info.get("upstream_dns", [])
        if upstream not in upstreams:
            upstreams.append(upstream)
        await adguard.set_upstream_dns(upstreams)
        await log_action(message.from_user.id, "adguard_add_upstream", upstream)
        await message.answer(f"✅ Upstream <code>{upstream}</code> добавлен", reply_markup=back_kb("adguard:upstream:list"), parse_mode="HTML")
    except AdGuardAPIError as e:
        await message.answer(t("error", msg=str(e)))


@router.callback_query(F.data.startswith("adguard:upstream:del:"))
async def cb_adguard_upstream_del(callback: CallbackQuery) -> None:
    await callback.answer()
    idx = int(callback.data.split(":")[3])
    try:
        dns_info = await adguard.get_dns_info()
        upstreams = dns_info.get("upstream_dns", [])
        if idx < len(upstreams):
            removed = upstreams.pop(idx)
            await adguard.set_upstream_dns(upstreams)
            await log_action(callback.from_user.id, "adguard_del_upstream", removed)
            await callback.message.answer(f"🗑 Upstream <code>{removed}</code> удалён", parse_mode="HTML")
    except AdGuardAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Filter rules ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adguard:rules:"))
async def cb_adguard_rules(callback: CallbackQuery) -> None:
    await callback.answer()
    page = int(callback.data.split(":")[2])
    try:
        rules = await adguard.get_user_rules()
    except AdGuardAPIError as e:
        await callback.message.edit_text(t("error", msg=str(e)), reply_markup=back_kb("menu:adguard"))
        return

    if not rules:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="➕ Добавить правило", callback_data="adguard:rule:add"))
        builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:adguard"))
        await callback.message.edit_text(
            "📋 <b>Правила фильтрации</b>\n\n<i>Правил нет</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    page_items, page, total_pages = paginate(rules, page, ITEMS_PER_PAGE)
    items = []
    for idx_in_page, rule in enumerate(page_items):
        abs_idx = (page - 1) * ITEMS_PER_PAGE + idx_in_page
        items.append({
            "label": f"🗑 {rule[:50]}{'…' if len(rule) > 50 else ''}",
            "callback_data": f"adguard:rule:del:{abs_idx}",
        })

    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(InlineKeyboardButton(text=item["label"], callback_data=item["callback_data"]))
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text=t("prev"), callback_data=f"adguard:rules:{page-1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text=t("next"), callback_data=f"adguard:rules:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="adguard:rule:add"),
        InlineKeyboardButton(text=t("back"), callback_data="menu:adguard"),
    )
    await callback.message.edit_text(
        f"📋 <b>Правила фильтрации</b> [{len(rules)}]\n<i>Нажмите на правило чтобы удалить</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adguard:rule:add")
async def cb_adguard_rule_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdGuardFSM.waiting_filter_rule)
    await callback.message.answer(t("ask_filter_rule"), reply_markup=back_kb("adguard:rules:1"))


@router.message(AdGuardFSM.waiting_filter_rule)
async def fsm_adguard_filter_rule(message: Message, state: FSMContext) -> None:
    await state.clear()
    rule = message.text.strip()
    try:
        await adguard.add_filter_rule(rule)
        await log_action(message.from_user.id, "adguard_add_rule", rule)
        await message.answer(
            f"✅ Правило добавлено:\n<code>{rule}</code>",
            reply_markup=back_kb("adguard:rules:1"),
            parse_mode="HTML",
        )
    except AdGuardAPIError as e:
        await message.answer(t("error", msg=str(e)))


@router.callback_query(F.data.startswith("adguard:rule:del:"))
async def cb_adguard_rule_del(callback: CallbackQuery) -> None:
    await callback.answer()
    idx = int(callback.data.split(":")[3])
    try:
        rules = await adguard.get_user_rules()
        if idx < len(rules):
            rule = rules[idx]
            await adguard.remove_filter_rule(rule)
            await log_action(callback.from_user.id, "adguard_del_rule", rule)
            await callback.message.answer(f"🗑 Правило удалено:\n<code>{rule}</code>", parse_mode="HTML")
    except AdGuardAPIError as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Change password ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "adguard:password")
async def cb_adguard_password(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdGuardFSM.waiting_password)
    await callback.message.answer(t("ask_new_password"), reply_markup=back_kb("menu:adguard"))


@router.message(AdGuardFSM.waiting_password)
async def fsm_adguard_password(message: Message, state: FSMContext) -> None:
    await state.clear()
    password = message.text.strip()
    if len(password) < 8:
        await message.answer("Пароль должен быть не менее 8 символов.")
        return
    try:
        await adguard.change_password(password)
        await log_action(message.from_user.id, "adguard_change_password")
        await message.answer("✅ Пароль AdGuard изменён.", reply_markup=back_kb("menu:adguard"))
    except AdGuardAPIError as e:
        await message.answer(t("error", msg=str(e)))


# ─── Sync clients from Sing-Box ──────────────────────────────────────────────

@router.callback_query(F.data == "adguard:sync")
async def cb_adguard_sync(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        sb_clients = await sui.get_clients()
        ag_clients = await adguard.get_clients()
        ag_names = {c["name"] for c in ag_clients}

        added = 0
        for c in sb_clients:
            name = c.get("name", c.get("email", ""))
            if name and name not in ag_names:
                await adguard.add_client({
                    "name": name,
                    "ids": [],
                    "use_global_settings": True,
                    "use_global_blocked_services": True,
                    "filtering_enabled": True,
                    "safebrowsing_enabled": True,
                })
                added += 1

        await log_action(callback.from_user.id, "adguard_sync_clients", f"added={added}")
        await callback.message.answer(
            f"✅ Синхронизировано {added} новых клиентов в AdGuard.",
            reply_markup=back_kb("menu:adguard"),
        )
    except (SuiAPIError, AdGuardAPIError) as e:
        await callback.message.answer(t("error", msg=str(e)))
