"""Server status, logs, restart, SSH port - thin wrapper over /api/server/ and settings."""
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from api.routers.settings_router import get_runtime
from bot.api_client import APIError, server_api, settings_api
from bot.keyboards.main import kb_back
from bot.texts import t

router = Router()


class SshPortFSM(StatesGroup):
    port = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


def _container_display(data: dict) -> str:
    configured = str(data.get("container") or "N/A")
    resolved = str(data.get("resolved_container") or configured)
    if resolved != configured:
        return f"{configured} -> {resolved}"
    return configured


def _short_error(data: dict, fallback_ru: str = "Неизвестная ошибка", fallback_en: str = "Unknown error") -> str:
    raw = str(data.get("error") or _txt(fallback_ru, fallback_en)).strip()
    if len(raw) > 450:
        raw = raw[-450:]
    return raw


@router.callback_query(F.data == "menu_server")
async def cb_server_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    from bot.keyboards.main import kb_server

    try:
        status = await server_api.status()
        running = status.get("running", False)
        icon = "🟢" if running else "🔴"
        text = f"{icon} Sing-Box: {_txt('запущен', 'running') if running else _txt('остановлен', 'stopped')}"

        warning = str(status.get("warning") or "").strip()
        error = str(status.get("error") or "").strip()
        if warning:
            text += f"\n⚠️ {warning}"
        if error:
            text += f"\n❌ {_short_error(status)}"
    except APIError as e:
        text = f"❌ {e.detail}"

    await cq.message.edit_text(text, reply_markup=kb_server())


@router.callback_query(F.data == "server_status")
async def cb_server_status(cq: CallbackQuery):
    try:
        status = await server_api.status()
        running = status.get("running", False)
        icon = "🟢" if running else "🔴"
        msg = (
            f"{icon} Sing-Box: {_txt('запущен', 'running') if running else _txt('остановлен', 'stopped')}\n"
            f"{_txt('Контейнер', 'Container')}: {_container_display(status)}"
        )

        warning = str(status.get("warning") or "").strip()
        error = str(status.get("error") or "").strip()
        if warning:
            msg += f"\n⚠️ {warning}"
        if error:
            msg += f"\n❌ {_short_error(status)}"
    except APIError as e:
        msg = f"❌ {e.detail}"

    await cq.answer()
    await cq.message.answer(msg, reply_markup=kb_back("menu_server"))


@router.callback_query(F.data == "server_logs")
async def cb_server_logs(cq: CallbackQuery):
    await cq.answer(_txt("Загружаю логи…", "Loading logs…"))
    try:
        data = await server_api.logs(150)
        lines = data.get("logs") or []
        container = escape(_container_display(data))
        warning = str(data.get("warning") or "").strip()
        error = str(data.get("error") or "").strip()

        if not lines:
            if error:
                err = escape(_short_error(data))
                text = (
                    f"❌ <b>{_txt('Не удалось загрузить логи', 'Failed to load logs')}</b>\n"
                    f"{_txt('Контейнер', 'Container')}: <code>{container}</code>\n"
                    f"<pre>{err}</pre>"
                )
            else:
                text = (
                    f"📋 {_txt('Логов пока нет', 'No logs')}\n"
                    f"{_txt('Контейнер', 'Container')}: <code>{container}</code>"
                )
        else:
            raw = "\n".join(lines[-80:])
            if len(raw) > 3200:
                raw = "...\n" + raw[-3200:]
            text = (
                f"📋 <b>{_txt('Последние логи', 'Recent logs')}:</b>\n"
                f"{_txt('Контейнер', 'Container')}: <code>{container}</code>\n"
                f"<pre>{escape(raw)}</pre>"
            )
            if warning:
                text += f"\n⚠️ <i>{escape(warning)}</i>"
    except APIError as e:
        text = f"❌ {escape(str(e.detail))}"
    except Exception as e:
        text = f"❌ {escape(str(e))}"

    await cq.message.answer(text, parse_mode="HTML", reply_markup=kb_back("menu_server"))


@router.callback_query(F.data == "server_restart")
async def cb_server_restart(cq: CallbackQuery):
    await cq.answer(_txt("Перезапускаю…", "Restarting…"))
    try:
        data = await server_api.restart()
        if data.get("success"):
            text = _txt("✅ Sing-Box перезапущен", "✅ Sing-Box restarted")
            warning = str(data.get("warning") or "").strip()
            if warning:
                text += f"\n⚠️ {warning}"
        else:
            text = (
                f"❌ {_txt('Перезапуск не удался', 'Restart failed')}\n"
                f"{_txt('Контейнер', 'Container')}: {_container_display(data)}\n"
                f"{_txt('Причина', 'Reason')}: {_short_error(data)}"
            )
    except APIError as e:
        text = f"❌ {e.detail}"

    await cq.message.answer(text, reply_markup=kb_back("menu_server"))


@router.callback_query(F.data == "server_reload")
async def cb_server_reload(cq: CallbackQuery):
    await cq.answer(_txt("Перечитываю конфиг…", "Reloading…"))
    try:
        data = await server_api.reload()
        if data.get("success"):
            text = _txt("✅ Конфиг перечитан", "✅ Config reloaded")
            note = str(data.get("note") or "").strip()
            warning = str(data.get("warning") or "").strip()
            if note:
                text += f"\nℹ️ {note}"
            if warning:
                text += f"\n⚠️ {warning}"
        else:
            text = (
                f"❌ {_txt('Перечитывание не удалось', 'Reload failed')}\n"
                f"{_txt('Контейнер', 'Container')}: {_container_display(data)}\n"
                f"{_txt('Причина', 'Reason')}: {_short_error(data)}"
            )
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
        reply_markup=kb_back("menu_maintenance"),
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
        await msg.answer(t("ssh_port_invalid"), reply_markup=kb_back("menu_maintenance"), parse_mode="HTML")
        return

    await state.clear()
    try:
        await settings_api.set("ssh_port", str(p))
        await msg.answer(
            t("ssh_port_saved", port=str(p)),
            reply_markup=kb_back("menu_maintenance"),
            parse_mode="HTML",
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_maintenance"))
