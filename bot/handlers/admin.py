import io
import json
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, delete

from bot.database import async_session, Admin, AuditLog
from bot.keyboards.main import back_kb
from bot.texts import t
from bot.middleware.auth import log_action
from bot.config import settings

router = Router()


class AdminFSM(StatesGroup):
    waiting_add_id = State()
    waiting_del_id = State()


# ─── Menu ──────────────────────────────────────────────────────────────────────

def admin_menu_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("admin_list"), callback_data="admin:list"),
        InlineKeyboardButton(text=t("admin_add"), callback_data="admin:add"),
    )
    builder.row(
        InlineKeyboardButton(text=t("admin_backup"), callback_data="admin:backup"),
        InlineKeyboardButton(text="📋 Audit Log", callback_data="admin:audit"),
    )
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:main"))
    return builder.as_markup()


@router.callback_query(F.data == "menu:admin")
async def cb_admin_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(t("admin_menu"), reply_markup=admin_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ─── Admin list ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:list")
async def cb_admin_list(callback: CallbackQuery) -> None:
    await callback.answer()
    static_ids = settings.admin_ids_list
    async with async_session() as session:
        result = await session.execute(select(Admin).where(Admin.is_active == True))
        db_admins = result.scalars().all()

    lines = ["👮 <b>Администраторы</b>\n"]
    if static_ids:
        lines.append("<b>Из .env:</b>")
        for uid in static_ids:
            lines.append(f"  • <code>{uid}</code> (статичный)")
    if db_admins:
        lines.append("\n<b>Из базы данных:</b>")
        for a in db_admins:
            uname = f"@{a.username}" if a.username else "—"
            lines.append(f"  • <code>{a.telegram_id}</code> {uname}")

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("admin_add"), callback_data="admin:add"),
    )
    for a in db_admins:
        builder.row(InlineKeyboardButton(
            text=f"🗑 {a.telegram_id} {('@' + a.username) if a.username else ''}",
            callback_data=f"admin:del_confirm:{a.telegram_id}",
        ))
    builder.row(InlineKeyboardButton(text=t("back"), callback_data="menu:admin"))
    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")


# ─── Add admin ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:add")
async def cb_admin_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminFSM.waiting_add_id)
    await callback.message.answer(t("ask_admin_id"), reply_markup=back_kb("menu:admin"))


@router.message(AdminFSM.waiting_add_id)
async def fsm_admin_add(message: Message, state: FSMContext) -> None:
    await state.clear()
    try:
        new_id = int(message.text.strip())
    except ValueError:
        await message.answer("Введите числовой Telegram ID.")
        return

    async with async_session() as session:
        existing = await session.execute(
            select(Admin).where(Admin.telegram_id == new_id)
        )
        if existing.scalar_one_or_none():
            await message.answer("Этот пользователь уже является администратором.")
            return
        username = None
        try:
            chat = await message.bot.get_chat(new_id)
            username = chat.username
        except Exception:
            pass
        admin = Admin(telegram_id=new_id, username=username, added_by=message.from_user.id)
        session.add(admin)
        await session.commit()

    await log_action(message.from_user.id, "add_admin", f"id={new_id}")
    await message.answer(t("admin_added"), reply_markup=back_kb("menu:admin"))


# ─── Delete admin ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:del_confirm:"))
async def cb_admin_del_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    tid = int(callback.data.split(":")[2])
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:del:{tid}"),
        InlineKeyboardButton(text=t("cancel"), callback_data="admin:list"),
    )
    await callback.message.edit_text(f"❓ Удалить администратора <code>{tid}</code>?", reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin:del:"))
async def cb_admin_del(callback: CallbackQuery) -> None:
    await callback.answer()
    tid = int(callback.data.split(":")[2])
    if tid in settings.admin_ids_list:
        await callback.message.edit_text(
            "❌ Нельзя удалить администратора из .env. Измените ADMIN_IDS в файле конфигурации.",
            reply_markup=back_kb("admin:list"),
        )
        return
    async with async_session() as session:
        result = await session.execute(select(Admin).where(Admin.telegram_id == tid))
        admin = result.scalar_one_or_none()
        if admin:
            await session.delete(admin)
            await session.commit()
    await log_action(callback.from_user.id, "del_admin", f"id={tid}")
    await callback.message.edit_text(t("admin_removed"), reply_markup=back_kb("admin:list"))


# ─── Backup ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:backup")
async def cb_admin_backup(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        from bot.services.sui_api import sui
        config = await sui.get_config()
        clients = await sui.get_clients()
        inbounds = await sui.get_inbounds()

        backup = {
            "timestamp": datetime.utcnow().isoformat(),
            "config": config,
            "clients": clients if isinstance(clients, list) else [],
            "inbounds": inbounds if isinstance(inbounds, list) else [],
        }
        content = json.dumps(backup, indent=2, ensure_ascii=False)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file = BufferedInputFile(content.encode(), filename=f"backup_{ts}.json")
        await log_action(callback.from_user.id, "backup")
        await callback.message.answer_document(
            file,
            caption=f"💾 <b>Бэкап</b> от {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
            parse_mode="HTML",
        )
    except Exception as e:
        await callback.message.answer(t("error", msg=str(e)))


# ─── Audit Log ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:audit")
async def cb_admin_audit(callback: CallbackQuery) -> None:
    await callback.answer()
    async with async_session() as session:
        result = await session.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(30)
        )
        logs = result.scalars().all()

    if not logs:
        await callback.message.edit_text("📋 Лог пустой.", reply_markup=back_kb("menu:admin"))
        return

    lines = ["📋 <b>Audit Log</b> (последние 30)\n"]
    for log in logs:
        ts = log.created_at.strftime("%m-%d %H:%M")
        details = f" — {log.details[:40]}" if log.details else ""
        lines.append(f"<code>{ts}</code> [{log.telegram_id}] <b>{log.action}</b>{details}")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_kb("menu:admin"),
        parse_mode="HTML",
    )
