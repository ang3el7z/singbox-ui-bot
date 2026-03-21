"""
Bot handlers for client subscription template management.

Menu flow:
  ⚙️ Settings → 📋 Templates
    - list all templates (name, label, is_default)
    - tap one → detail: set as default, delete
    - Create new template (paste JSON)

Per-client template assignment (from client detail):
  👤 Client detail → 🎨 Template → list templates → select one → assigned
"""
import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from api.routers.settings_router import get_runtime
from bot.api_client import client_tmpl_api, clients_api, APIError
from bot.keyboards.main import kb_back

router = Router()


class CreateTemplateFSM(StatesGroup):
    name  = State()
    label = State()
    json  = State()


def _is_ru() -> bool:
    return get_runtime("bot_lang", "ru") == "ru"


def _txt(ru: str, en: str) -> str:
    return ru if _is_ru() else en


# ─── Template list ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_templates")
async def cb_templates_menu(cq: CallbackQuery):
    try:
        templates = await client_tmpl_api.list()
    except APIError as e:
        await cq.message.edit_text(f"❌ {e.detail}", reply_markup=kb_back("main_menu"))
        return

    if not templates:
        text = _txt("📋 <b>Шаблоны</b>\n\nШаблоны не найдены.", "📋 <b>Templates</b>\n\nNo templates found.")
    else:
        lines = [_txt("📋 <b>Шаблоны подписки</b>\n", "📋 <b>Subscription Templates</b>\n")]
        for t in templates:
            star = _txt(" ⭐ по умолчанию", " ⭐ default") if t.get("is_default") else ""
            lines.append(f"• <b>{t['label']}</b> (<code>{t['name']}</code>){star}")
        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    for t in templates:
        star = "⭐ " if t.get("is_default") else ""
        builder.button(text=f"{star}{t['label']}", callback_data=f"tmpl_detail_{t['id']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=_txt("➕ Создать шаблон", "➕ Create template"), callback_data="tmpl_create"))
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="main_menu"))

    await cq.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ─── Template detail ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tmpl_detail_"))
async def cb_template_detail(cq: CallbackQuery):
    tid = int(cq.data.split("_")[-1])
    try:
        t = await client_tmpl_api.get(tid)
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return

    star = _txt(" ⭐ (по умолчанию)", " ⭐ (default)") if t.get("is_default") else ""
    text = (
        f"📋 <b>{t['label']}</b>{star}\n"
        f"{_txt('Имя', 'Name')}: <code>{t['name']}</code>\n"
        f"ID: {t['id']}\n\n"
        f"{_txt('Превью JSON-конфига (первые 300 символов)', 'Config JSON preview (first 300 chars)')}:\n"
        f"<pre>{t['config_json'][:300]}...</pre>"
    )

    builder = InlineKeyboardBuilder()
    if not t.get("is_default"):
        builder.button(text=_txt("⭐ Сделать по умолчанию", "⭐ Set as default"), callback_data=f"tmpl_setdef_{tid}")
    builder.button(text=_txt("📄 Полный JSON", "📄 View full JSON"), callback_data=f"tmpl_json_{tid}")
    if not t.get("is_default"):
        builder.button(text=_txt("🗑 Удалить", "🗑 Delete"), callback_data=f"tmpl_delete_{tid}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Назад", "⬅️ Back"), callback_data="menu_templates"))

    await cq.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("tmpl_json_"))
async def cb_template_json(cq: CallbackQuery):
    tid = int(cq.data.split("_")[-1])
    try:
        t = await client_tmpl_api.get(tid)
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return

    # Pretty-print and split if needed
    pretty = json.dumps(json.loads(t["config_json"]), indent=2, ensure_ascii=False)
    # Send as file to avoid message length limits
    from aiogram.types import BufferedInputFile
    file = BufferedInputFile(pretty.encode("utf-8"), filename=f"{t['name']}.json")
    await cq.message.answer_document(
        file,
        caption=_txt(f"📄 Шаблон: <b>{t['label']}</b>", f"📄 Template: <b>{t['label']}</b>"),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("tmpl_setdef_"))
async def cb_template_setdefault(cq: CallbackQuery):
    tid = int(cq.data.split("_")[-1])
    try:
        t = await client_tmpl_api.set_default(tid)
        await cq.answer(_txt(f"✅ '{t['label']}' теперь шаблон по умолчанию", f"✅ '{t['label']}' is now the default template"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return
    # Refresh list
    await cb_templates_menu(cq)


@router.callback_query(F.data.startswith("tmpl_delete_"))
async def cb_template_delete(cq: CallbackQuery):
    tid = int(cq.data.split("_")[-1])
    try:
        await client_tmpl_api.delete(tid)
        await cq.answer(_txt("✅ Удалено", "✅ Deleted"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return
    await cb_templates_menu(cq)


# ─── Create template FSM ──────────────────────────────────────────────────────

@router.callback_query(F.data == "tmpl_create")
async def cb_template_create(cq: CallbackQuery, state: FSMContext):
    await state.set_state(CreateTemplateFSM.name)
    await cq.message.answer(
        _txt(
            "📋 <b>Создание шаблона</b>\n\n"
            "Шаг 1/3: Введите короткое внутреннее имя (без пробелов, например <code>my_router</code>):",
            "📋 <b>Create template</b>\n\n"
            "Step 1/3: Enter a short internal name (no spaces, e.g. <code>my_router</code>):",
        ),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(CreateTemplateFSM.name)
async def fsm_tmpl_name(msg: Message, state: FSMContext):
    name = msg.text.strip().replace(" ", "_")
    await state.update_data(name=name)
    await state.set_state(CreateTemplateFSM.label)
    await msg.answer(
        _txt(
            "Шаг 2/3: Введите отображаемое название (например <b>Мой OpenWRT Router</b>):",
            "Step 2/3: Enter a display label (e.g. <b>My OpenWRT Router</b>):",
        ),
        parse_mode="HTML",
    )


@router.message(CreateTemplateFSM.label)
async def fsm_tmpl_label(msg: Message, state: FSMContext):
    await state.update_data(label=msg.text.strip())
    await state.set_state(CreateTemplateFSM.json)
    await msg.answer(
        _txt(
            "Шаг 3/3: Вставьте полный JSON-конфиг клиента sing-box.\n\n"
            "⚠️ Массив <code>outbounds</code> ОБЯЗАТЕЛЬНО должен содержать этот placeholder "
            "(он будет заменён на реальный прокси):\n"
            '<pre>{"tag": "proxy", "type": "__proxy__"}</pre>',
            "Step 3/3: Paste the full sing-box client config JSON.\n\n"
            "⚠️ The <code>outbounds</code> array MUST contain this placeholder (it will be replaced with the real proxy):\n"
            '<pre>{"tag": "proxy", "type": "__proxy__"}</pre>',
        ),
        parse_mode="HTML",
    )


@router.message(CreateTemplateFSM.json)
async def fsm_tmpl_json(msg: Message, state: FSMContext):
    raw = msg.text.strip()
    # Validate JSON
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        await msg.answer(_txt(f"❌ Невалидный JSON: {e}\n\nПопробуйте ещё раз:", f"❌ Invalid JSON: {e}\n\nTry again:"))
        return

    outbounds = cfg.get("outbounds", [])
    if not any(ob.get("type") == "__proxy__" for ob in outbounds):
        await msg.answer(
            _txt(
                '❌ Отсутствует placeholder outbound.\n\n'
                'Добавьте это в массив <code>outbounds</code>:\n'
                '<pre>{"tag": "proxy", "type": "__proxy__"}</pre>\n\nПопробуйте снова:',
                '❌ Missing placeholder outbound.\n\n'
                'Add this to your <code>outbounds</code> array:\n'
                '<pre>{"tag": "proxy", "type": "__proxy__"}</pre>\n\nTry again:',
            ),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    await state.clear()
    try:
        t = await client_tmpl_api.create(
            name=data["name"],
            label=data["label"],
            config_json=json.dumps(cfg),
        )
        await msg.answer(
            _txt(
                f"✅ Шаблон <b>{t['label']}</b> создан!\n"
                f"Имя: <code>{t['name']}</code>  ID: {t['id']}",
                f"✅ Template <b>{t['label']}</b> created!\n"
                f"Name: <code>{t['name']}</code>  ID: {t['id']}",
            ),
            parse_mode="HTML",
            reply_markup=kb_back("menu_templates"),
        )
    except APIError as e:
        await msg.answer(f"❌ {e.detail}", reply_markup=kb_back("menu_templates"))


# ─── Per-client template assignment ──────────────────────────────────────────

@router.callback_query(F.data.startswith("client_tmpl_"))
async def cb_client_template(cq: CallbackQuery):
    """Show list of templates to assign to this client."""
    cid = int(cq.data.split("_")[-1])
    try:
        templates = await client_tmpl_api.list()
        client   = await clients_api.get(cid)
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return

    current_tid = client.get("template_id")
    builder = InlineKeyboardBuilder()
    for t in templates:
        mark = "✅ " if t["id"] == current_tid else ("⭐ " if t.get("is_default") and current_tid is None else "")
        builder.button(text=f"{mark}{t['label']}", callback_data=f"client_set_tmpl_{cid}_{t['id']}")
    # Option to reset to default
    if current_tid is not None:
        builder.button(text=_txt("↩️ Использовать шаблон по умолчанию", "↩️ Use default template"), callback_data=f"client_set_tmpl_{cid}_0")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text=_txt("⬅️ Отмена", "⬅️ Cancel"), callback_data=f"client_detail_{cid}"))

    await cq.message.edit_text(
        _txt(
            f"🎨 Выберите шаблон для <b>{client.get('name', '?')}</b>\n\n"
            f"⭐ = шаблон по умолчанию  ✅ = назначен сейчас",
            f"🎨 Choose template for <b>{client.get('name', '?')}</b>\n\n"
            f"⭐ = default template  ✅ = currently assigned",
        ),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("client_set_tmpl_"))
async def cb_client_set_template(cq: CallbackQuery):
    parts = cq.data.split("_")
    # client_set_tmpl_{cid}_{tid}
    cid = int(parts[3])
    tid = int(parts[4])
    new_tid = None if tid == 0 else tid
    try:
        await clients_api.update(cid, template_id=new_tid)
        label = _txt("по умолчанию", "default") if new_tid is None else str(new_tid)
        try:
            templates = await client_tmpl_api.list()
            t = next((x for x in templates if x["id"] == new_tid), None)
            if t:
                label = t["label"]
        except Exception:
            pass
        await cq.answer(_txt(f"✅ Шаблон установлен: {label}", f"✅ Template set: {label}"))
    except APIError as e:
        await cq.answer(f"❌ {e.detail}", show_alert=True)
        return

    # Go back to client detail
    from bot.handlers.clients import cb_client_detail
    cq.data = f"client_detail_{cid}"
    await cb_client_detail(cq)
