"""AdGuard Home management — thin wrapper over /api/adguard/"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from api.routers.settings_router import get_runtime
from bot.api_client import adguard_api, APIError
from bot.keyboards.main import kb_back, kb_adguard_menu

router = Router()


class AddUpstreamFSM(StatesGroup):
    value = State()


class AddRuleFSM(StatesGroup):
    value = State()


class ChangePasswordFSM(StatesGroup):
    value = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


@router.callback_query(F.data == "menu_adguard")
async def cb_adguard_menu(cq: CallbackQuery):
    try:
        status = await adguard_api.status()
        avail = status.get("available", True)
        if not avail:
            text = _txt("⚠️ AdGuard Home недоступен", "⚠️ AdGuard Home not available")
        else:
            prot = status.get("protection_enabled", False)
            icon = "🟢" if prot else "🔴"
            text = (
                f"{icon} AdGuard: {_txt('включен', 'enabled')}"
                if prot
                else f"{icon} AdGuard: {_txt('выключен', 'disabled')}"
            )
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
            f"📊 <b>{_txt('Статистика AdGuard', 'AdGuard Stats')}</b>\n"
            f"{_txt('DNS-запросы', 'DNS queries')}: {dns}\n"
            f"{_txt('Заблокировано', 'Blocked')}: {blocked}\n"
            f"{_txt('Среднее время', 'Avg time')}: {avg:.1f}ms"
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
        state_str = _txt("включена", "enabled") if enabled else _txt("выключена", "disabled")
        await cq.answer(_txt(f"✅ Защита {state_str}", f"✅ Protection {state_str}"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)


@router.callback_query(F.data == "adguard_dns")
async def cb_adguard_dns(cq: CallbackQuery):
    try:
        info = await adguard_api.dns()
        upstreams = info.get("upstream_dns", [])
        if upstreams:
            text = _txt("🌐 <b>Upstream DNS:</b>\n", "🌐 <b>Upstream DNS:</b>\n") + "\n".join(f"• {u}" for u in upstreams)
        else:
            text = _txt("🌐 Upstream DNS не настроен", "🌐 No upstream DNS configured")
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    from bot.keyboards.main import kb_adguard_dns
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_adguard_dns())


@router.callback_query(F.data == "adguard_add_upstream")
async def cb_adguard_add_upstream(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddUpstreamFSM.value)
    await cq.message.answer(
        _txt(
            "Введите upstream DNS (например, 8.8.8.8 или tls://dns.google):",
            "Enter upstream DNS (e.g. 8.8.8.8 or tls://dns.google):",
        )
    )
    await cq.answer()


@router.message(AddUpstreamFSM.value)
async def fsm_add_upstream(msg: Message, state: FSMContext):
    await state.clear()
    try:
        await adguard_api.add_upstream(msg.text.strip())
        await msg.answer(
            _txt(f"✅ Добавлено: {msg.text.strip()}", f"✅ Added: {msg.text.strip()}"),
            reply_markup=kb_back("adguard_dns"),
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_adguard"))


@router.callback_query(F.data == "adguard_rules")
async def cb_adguard_rules(cq: CallbackQuery):
    try:
        data = await adguard_api.rules()
        rules = data.get("rules", [])
        if rules:
            text = _txt("🚫 <b>Правила фильтрации:</b>\n", "🚫 <b>Filter Rules:</b>\n") + "\n".join(
                f"• <code>{r}</code>" for r in rules[:20]
            )
            if len(rules) > 20:
                text += _txt(f"\n…и ещё {len(rules)-20}", f"\n…and {len(rules)-20} more")
        else:
            text = _txt("🚫 Нет правил фильтрации", "🚫 No filter rules")
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    from bot.keyboards.main import kb_adguard_rules
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_adguard_rules())


@router.callback_query(F.data == "adguard_add_rule")
async def cb_adguard_add_rule(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddRuleFSM.value)
    await cq.message.answer(
        _txt("Введите правило фильтрации (например, ||example.com^):", "Enter filter rule (e.g. ||example.com^):")
    )
    await cq.answer()


@router.message(AddRuleFSM.value)
async def fsm_add_rule(msg: Message, state: FSMContext):
    await state.clear()
    try:
        await adguard_api.add_rule(msg.text.strip())
        await msg.answer(_txt("✅ Правило добавлено", "✅ Rule added"), reply_markup=kb_back("menu_adguard"))
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_adguard"))


@router.callback_query(F.data == "adguard_change_password")
async def cb_adguard_change_password(cq: CallbackQuery, state: FSMContext):
    await state.set_state(ChangePasswordFSM.value)
    await cq.message.answer(
        _txt("Введите новый пароль AdGuard (минимум 8 символов):", "Enter new AdGuard password (min 8 chars):")
    )
    await cq.answer()


@router.message(ChangePasswordFSM.value)
async def fsm_adguard_password(msg: Message, state: FSMContext):
    await state.clear()
    try:
        await adguard_api.change_password(msg.text.strip())
        await msg.answer(_txt("✅ Пароль изменён", "✅ Password changed"), reply_markup=kb_back("menu_adguard"))
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_adguard"))


@router.callback_query(F.data == "adguard_sync")
async def cb_adguard_sync(cq: CallbackQuery):
    try:
        result = await adguard_api.sync_clients()
        added = result.get("added", 0)
        await cq.answer(_txt(f"✅ Синхронизировано, добавлено: {added}", f"✅ Synced, added: {added}"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
