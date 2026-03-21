"""Sing-Box section: status, logs, reload/restart, SSH port."""
import asyncio
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from api.routers.settings_router import get_runtime
from bot.api_client import APIError, server_api, settings_api
from bot.keyboards.main import kb_back, kb_server
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


def _status_block(data: dict) -> str:
    running = bool(data.get("running"))
    status_word = _txt("включен", "running") if running else _txt("выключен", "stopped")
    lines = [
        f"{_txt('Состояние', 'State')}: <b>{status_word}</b>",
        f"{_txt('Контейнер', 'Container')}: <code>{escape(_container_display(data))}</code>",
    ]
    warning = str(data.get("warning") or "").strip()
    error = str(data.get("error") or "").strip()
    if warning:
        lines.append(f"{_txt('Предупреждение', 'Warning')}: {escape(warning)}")
    if error:
        lines.append(f"{_txt('Ошибка', 'Error')}: {escape(_short_error(data))}")
    return "\n".join(lines)


async def _safe_answer(cq: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    try:
        await cq.answer(text=text, show_alert=show_alert)
    except Exception:
        pass


async def _edit_current(
    cq: CallbackQuery,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> None:
    try:
        await cq.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await cq.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def _show_wait(cq: CallbackQuery, text_ru: str, text_en: str) -> None:
    try:
        await cq.message.bot.send_chat_action(cq.message.chat.id, ChatAction.TYPING)
    except Exception:
        pass
    await _edit_current(
        cq,
        f"<b>Sing-Box</b>\n\n{_txt(text_ru, text_en)}",
        reply_markup=kb_server(),
    )


async def _render_server_home(cq: CallbackQuery) -> None:
    try:
        status = await server_api.status()
        text = f"<b>Sing-Box</b>\n\n{_status_block(status)}"
    except APIError as e:
        text = f"<b>Sing-Box</b>\n\n{_txt('Ошибка', 'Error')}: {escape(e.detail)}"
    await _edit_current(cq, text, reply_markup=kb_server())


@router.callback_query(F.data == "menu_server")
async def cb_server_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await _render_server_home(cq)
    await _safe_answer(cq)


@router.callback_query(F.data == "server_status")
async def cb_server_status(cq: CallbackQuery):
    await _render_server_home(cq)
    await _safe_answer(cq)


@router.callback_query(F.data == "server_logs")
async def cb_server_logs(cq: CallbackQuery):
    await _show_wait(cq, "Ждём ответ сервера...", "Waiting for server response...")
    try:
        data = await server_api.logs(150)
        logs = data.get("logs") or []
        container = escape(_container_display(data))
        warning = str(data.get("warning") or "").strip()
        error = str(data.get("error") or "").strip()
        if logs:
            raw = "\n".join(logs[-80:])
            if len(raw) > 3200:
                raw = "...\n" + raw[-3200:]
            text = (
                f"<b>{_txt('Логи Sing-Box', 'Sing-Box Logs')}</b>\n\n"
                f"{_txt('Контейнер', 'Container')}: <code>{container}</code>\n"
                f"<pre>{escape(raw)}</pre>"
            )
            if warning:
                text += f"\n{_txt('Предупреждение', 'Warning')}: {escape(warning)}"
        elif error:
            text = (
                f"<b>{_txt('Логи Sing-Box', 'Sing-Box Logs')}</b>\n\n"
                f"{_txt('Контейнер', 'Container')}: <code>{container}</code>\n"
                f"{_txt('Ошибка', 'Error')}: {escape(_short_error(data))}"
            )
        else:
            text = (
                f"<b>{_txt('Логи Sing-Box', 'Sing-Box Logs')}</b>\n\n"
                f"{_txt('Контейнер', 'Container')}: <code>{container}</code>\n"
                f"{_txt('Логи пока пустые', 'No logs yet')}"
            )
    except APIError as e:
        text = f"<b>{_txt('Логи Sing-Box', 'Sing-Box Logs')}</b>\n\n{_txt('Ошибка', 'Error')}: {escape(e.detail)}"
    except Exception as e:
        text = f"<b>{_txt('Логи Sing-Box', 'Sing-Box Logs')}</b>\n\n{_txt('Ошибка', 'Error')}: {escape(str(e))}"
    await _edit_current(cq, text, reply_markup=kb_back("menu_server"))
    await _safe_answer(cq)


@router.callback_query(F.data == "server_restart")
async def cb_server_restart(cq: CallbackQuery):
    await _show_wait(cq, "Выполняем перезапуск...", "Restarting...")
    try:
        data = await server_api.restart()
        if data.get("success"):
            text = f"<b>Sing-Box</b>\n\n{_txt('Перезапуск выполнен', 'Restart completed')}"
            warning = str(data.get("warning") or "").strip()
            if warning:
                text += f"\n{_txt('Предупреждение', 'Warning')}: {escape(warning)}"
        else:
            text = (
                f"<b>Sing-Box</b>\n\n"
                f"{_txt('Перезапуск не выполнен', 'Restart failed')}\n"
                f"{_txt('Контейнер', 'Container')}: <code>{escape(_container_display(data))}</code>\n"
                f"{_txt('Причина', 'Reason')}: {escape(_short_error(data))}"
            )
    except APIError as e:
        text = f"<b>Sing-Box</b>\n\n{_txt('Ошибка', 'Error')}: {escape(e.detail)}"
    await _edit_current(cq, text, reply_markup=kb_server())
    await _safe_answer(cq)


@router.callback_query(F.data == "server_reload")
async def cb_server_reload(cq: CallbackQuery):
    await _show_wait(cq, "Применяем конфигурацию...", "Applying configuration...")
    try:
        data = await server_api.reload()
        if (not data.get("success")) and "restarting" in str(data.get("error") or "").lower():
            await asyncio.sleep(2)
            retry = await server_api.reload()
            if retry.get("success"):
                data = retry
                data["note"] = _txt("Контейнер был в перезапуске, повтор выполнен успешно", "Container was restarting, retry succeeded")
        if data.get("success"):
            text = f"<b>Sing-Box</b>\n\n{_txt('Конфигурация применена', 'Configuration applied')}"
            note = str(data.get("note") or "").strip()
            warning = str(data.get("warning") or "").strip()
            if note:
                text += f"\n{_txt('Деталь', 'Detail')}: {escape(note)}"
            if warning:
                text += f"\n{_txt('Предупреждение', 'Warning')}: {escape(warning)}"
        else:
            text = (
                f"<b>Sing-Box</b>\n\n"
                f"{_txt('Конфигурация не применена', 'Configuration not applied')}\n"
                f"{_txt('Контейнер', 'Container')}: <code>{escape(_container_display(data))}</code>\n"
                f"{_txt('Причина', 'Reason')}: {escape(_short_error(data))}"
            )
    except APIError as e:
        text = f"<b>Sing-Box</b>\n\n{_txt('Ошибка', 'Error')}: {escape(e.detail)}"
    await _edit_current(cq, text, reply_markup=kb_server())
    await _safe_answer(cq)


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
    await _safe_answer(cq)


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
        await msg.answer(f"{_txt('Ошибка', 'Error')}: {e.detail}", reply_markup=kb_back("menu_maintenance"))
