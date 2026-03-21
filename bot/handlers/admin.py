"""Admin management — thin wrapper over /api/admin/"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from api.routers.settings_router import get_runtime
from bot.api_client import admin_api, APIError
from bot.keyboards.main import kb_back, kb_admin_menu

router = Router()


class AddAdminFSM(StatesGroup):
    telegram_id = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


@router.callback_query(F.data == "menu_admin")
async def cb_admin_menu(cq: CallbackQuery):
    await cq.message.edit_text(
        _txt("👑 <b>Панель админа</b>", "👑 <b>Admin Panel</b>"),
        reply_markup=kb_admin_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_list")
async def cb_admin_list(cq: CallbackQuery):
    try:
        admins = await admin_api.list_admins()
        if admins:
            lines = [f"• {a['telegram_id']} (@{a.get('username', 'N/A')})" for a in admins]
            text = _txt("👑 <b>Админы:</b>\n", "👑 <b>Admins:</b>\n") + "\n".join(lines)
        else:
            text = _txt("Дополнительных админов нет", "No additional admins")
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_admin"))


@router.callback_query(F.data == "admin_add")
async def cb_admin_add(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddAdminFSM.telegram_id)
    await cq.message.answer(_txt("Введите Telegram ID нового админа:", "Enter Telegram ID of new admin:"))
    await cq.answer()


@router.message(AddAdminFSM.telegram_id)
async def fsm_admin_id(msg: Message, state: FSMContext):
    await state.clear()
    try:
        tg_id = int(msg.text.strip())
    except ValueError:
        await msg.answer(_txt("❌ Неверный Telegram ID", "❌ Invalid Telegram ID"), reply_markup=kb_back("menu_admin"))
        return
    try:
        await admin_api.add_admin(tg_id)
        await msg.answer(
            _txt(f"✅ Админ {tg_id} добавлен", f"✅ Admin {tg_id} added"),
            reply_markup=kb_back("menu_admin"),
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_admin"))


@router.callback_query(F.data == "admin_audit_log")
async def cb_admin_audit_log(cq: CallbackQuery):
    try:
        logs = await admin_api.audit_log(30)
        if logs:
            lines = [f"• {l['created_at'][:16]} [{l['actor']}] {l['action']}" for l in logs]
            text = _txt("📋 <b>Журнал аудита:</b>\n<pre>", "📋 <b>Audit Log:</b>\n<pre>") + "\n".join(lines) + "</pre>"
        else:
            text = _txt("📋 Журнал аудита пуст", "📋 Audit log is empty")
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_admin"))


@router.callback_query(F.data == "admin_backup")
async def cb_admin_backup(cq: CallbackQuery):
    await cq.answer(_txt("Перенесено в Обслуживание", "Moved to Maintenance"), show_alert=True)
    await cq.message.answer(
        _txt("💾 Backup перенесён в: Обслуживание → Backup", "💾 Backup moved to: Maintenance → Backup"),
        reply_markup=kb_back("maint_backup_menu"),
    )
