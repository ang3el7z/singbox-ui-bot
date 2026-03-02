"""Server status, logs, restart — thin wrapper over /api/server/"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command

from bot.api_client import server_api, APIError
from bot.keyboards.main import kb_back
from bot.texts import t
from bot.utils import format_uptime

router = Router()


@router.callback_query(F.data == "menu_server")
async def cb_server_menu(cq: CallbackQuery):
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
