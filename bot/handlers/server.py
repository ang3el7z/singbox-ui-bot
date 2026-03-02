"""Server status, logs, restart, SSH port — thin wrapper over /api/server/ and settings."""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.api_client import server_api, settings_api, APIError
from bot.keyboards.main import kb_back
from bot.texts import t

router = Router()


class SshPortFSM(StatesGroup):
    port = State()


@router.callback_query(F.data == "menu_server")
async def cb_server_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    from bot.keyboards.main import kb_server
    try:
        status = await server_api.status()
        running = status.get("running", False)
        icon = "🟢" if running else "🔴"
        text = f"{icon} Sing-Box: {'running' if running else 'stopped'}"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.edit_text(text, reply_markup=kb_server())


@router.callback_query(F.data == "server_status")
async def cb_server_status(cq: CallbackQuery):
    try:
        status = await server_api.status()
        running = status.get("running", False)
        icon = "🟢" if running else "🔴"
        msg = f"{icon} Sing-Box: {'running' if running else 'stopped'}\nContainer: {status.get('container', 'N/A')}"
    except APIError as e:
        msg = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(msg, reply_markup=kb_back("menu_server"))


@router.callback_query(F.data == "server_logs")
async def cb_server_logs(cq: CallbackQuery):
    try:
        data = await server_api.logs(50)
        lines = data.get("logs", [])
        if not lines:
            text = "📋 No logs"
        else:
            last = lines[-30:]
            text = "📋 <b>Recent logs:</b>\n<pre>" + "\n".join(last) + "</pre>"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.answer()
    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_server"))


@router.callback_query(F.data == "server_restart")
async def cb_server_restart(cq: CallbackQuery):
    await cq.answer("Restarting…")
    try:
        data = await server_api.restart()
        if data.get("success"):
            text = "✅ Sing-Box restarted"
        else:
            text = "❌ Restart failed"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, reply_markup=kb_back("menu_server"))


@router.callback_query(F.data == "server_reload")
async def cb_server_reload(cq: CallbackQuery):
    await cq.answer("Reloading…")
    try:
        data = await server_api.reload()
        text = "✅ Config reloaded" if data.get("success") else "❌ Reload failed"
    except APIError as e:
        text = f"❌ {e.detail}"
    await cq.message.answer(text, reply_markup=kb_back("menu_server"))


@router.callback_query(F.data == "server_ssh_port")
async def cb_server_ssh_port(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        r = await settings_api.get("ssh_port")
        port = (r.get("value") or "22").strip()
    except APIError:
        port = "22"
    await state.set_state(SshPortFSM.port)
    await cq.message.edit_text(
        t("ssh_port_current", port=port),
        reply_markup=kb_back("menu_server"),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(SshPortFSM.port, F.text)
async def fsm_ssh_port(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    try:
        p = int(raw)
        if p < 1 or p > 65535:
            raise ValueError("out of range")
    except ValueError:
        await msg.answer(t("ssh_port_invalid"), reply_markup=kb_back("menu_server"), parse_mode="HTML")
        return
    await state.clear()
    try:
        await settings_api.set("ssh_port", str(p))
        await msg.answer(
            t("ssh_port_saved", port=str(p)),
            reply_markup=kb_back("menu_server"),
            parse_mode="HTML",
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_server"))
