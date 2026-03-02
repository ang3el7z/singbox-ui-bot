"""AdGuard Home management — thin wrapper over /api/adguard/"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.api_client import adguard_api, APIError
from bot.keyboards.main import kb_back, kb_adguard_menu

router = Router()


class AddUpstreamFSM(StatesGroup):
    value = State()


class AddRuleFSM(StatesGroup):
    value = State()


class ChangePasswordFSM(StatesGroup):
    value = State()


@router.callback_query(F.data == "menu_adguard")
async def cb_adguard_menu(cq: CallbackQuery):
    try:
        status = await adguard_api.status()
        avail = status.get("available", True)
        if not avail:
            text = "⚠️ AdGuard Home not available"
        else:
            prot = status.get("protection_enabled", False)
            icon = "🟢" if prot else "🔴"
            text = f"{icon} AdGuard: {'enabled' if prot else 'disabled'}"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.edit_text(text, reply_markup=kb_adguard_menu(), parse_mode="HTML")


@router.callback_query(F.data == "adguard_stats")
async def cb_adguard_stats(cq: CallbackQuery):
    try:
        stats = await adguard_api.stats()
        dns = stats.get("dns_queries", 0)
        blocked = stats.get("blocked_filtering", 0)
        avg = stats.get("avg_processing_time", 0)
        text = (
            f"📊 <b>AdGuard Stats</b>\n"
            f"DNS queries: {dns}\n"
            f"Blocked: {blocked}\n"
            f"Avg time: {avg:.1f}ms"
        )
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_adguard"))


@router.callback_query(F.data.startswith("adguard_protection_"))
async def cb_adguard_toggle(cq: CallbackQuery):
    enabled = cq.data.endswith("_on")
    try:
        await adguard_api.toggle(enabled)
        state_str = "enabled" if enabled else "disabled"
        await cq.answer(f"✅ Protection {state_str}")
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data == "adguard_dns")
async def cb_adguard_dns(cq: CallbackQuery):
    try:
        info = await adguard_api.dns()
        upstreams = info.get("upstream_dns", [])
        if upstreams:
            text = "🌐 <b>Upstream DNS:</b>\n" + "\n".join(f"• {u}" for u in upstreams)
        else:
            text = "🌐 No upstream DNS configured"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    from bot.keyboards.main import kb_adguard_dns
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_adguard_dns())


@router.callback_query(F.data == "adguard_add_upstream")
async def cb_adguard_add_upstream(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddUpstreamFSM.value)
    await cq.message.answer("Enter upstream DNS (e.g. 8.8.8.8 or tls://dns.google):")
    await cq.answer()


@router.message(AddUpstreamFSM.value)
async def fsm_add_upstream(msg: Message, state: FSMContext):
    await state.clear()
    try:
        result = await adguard_api.add_upstream(msg.text.strip())
        await msg.answer(f"✅ Added: {msg.text.strip()}", reply_markup=kb_back("adguard_dns"))
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_adguard"))


@router.callback_query(F.data == "adguard_rules")
async def cb_adguard_rules(cq: CallbackQuery):
    try:
        data = await adguard_api.rules()
        rules = data.get("rules", [])
        if rules:
            text = "🚫 <b>Filter Rules:</b>\n" + "\n".join(f"• <code>{r}</code>" for r in rules[:20])
            if len(rules) > 20:
                text += f"\n…and {len(rules)-20} more"
        else:
            text = "🚫 No filter rules"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    from bot.keyboards.main import kb_adguard_rules
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_adguard_rules())


@router.callback_query(F.data == "adguard_add_rule")
async def cb_adguard_add_rule(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddRuleFSM.value)
    await cq.message.answer("Enter filter rule (e.g. ||example.com^):")
    await cq.answer()


@router.message(AddRuleFSM.value)
async def fsm_add_rule(msg: Message, state: FSMContext):
    await state.clear()
    try:
        await adguard_api.add_rule(msg.text.strip())
        await msg.answer("✅ Rule added", reply_markup=kb_back("menu_adguard"))
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_adguard"))


@router.callback_query(F.data == "adguard_change_password")
async def cb_adguard_change_password(cq: CallbackQuery, state: FSMContext):
    await state.set_state(ChangePasswordFSM.value)
    await cq.message.answer("Enter new AdGuard password (min 8 chars):")
    await cq.answer()


@router.message(ChangePasswordFSM.value)
async def fsm_adguard_password(msg: Message, state: FSMContext):
    await state.clear()
    try:
        await adguard_api.change_password(msg.text.strip())
        await msg.answer("✅ Password changed", reply_markup=kb_back("menu_adguard"))
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_adguard"))


@router.callback_query(F.data == "adguard_sync")
async def cb_adguard_sync(cq: CallbackQuery):
    try:
        result = await adguard_api.sync_clients()
        await cq.answer(f"✅ Synced, added: {result.get('added', 0)}")
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
