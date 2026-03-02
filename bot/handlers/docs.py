"""
Documentation browser for the Telegram bot.
Fetches content from the API (lang is read from user's bot_lang setting).
Content is served in the user's chosen language — RU or EN only, not both.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.api_client import docs_api, settings_api

router = Router()

# Maximum Telegram message length
_CHUNK = 3800


async def _get_lang() -> str:
    """Return current bot language — always set at install time via .env / Settings."""
    result = await settings_api.get("bot_lang")
    return result.get("value", "ru") if isinstance(result, dict) else "ru"


def _split_md(text: str) -> list[str]:
    """Split markdown text into Telegram-safe chunks at paragraph boundaries."""
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = (current + "\n\n" + block).lstrip() if current else block
        if len(candidate) <= _CHUNK:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            while len(block) > _CHUNK:
                chunks.append(block[:_CHUNK])
                block = block[_CHUNK:]
            current = block
    if current.strip():
        chunks.append(current.strip())
    return chunks or ["(empty)"]


def _kb_doc_list(docs: list, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in docs:
        builder.row(InlineKeyboardButton(
            text=d["title"],
            callback_data=f"docs_open_{d['id']}_0",
        ))
    builder.row(InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu"))
    return builder.as_markup()


def _kb_page(doc_id: str, page: int, total: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"docs_open_{doc_id}_{page - 1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"docs_open_{doc_id}_{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(
        InlineKeyboardButton(text="📋 All docs", callback_data="menu_docs"),
        InlineKeyboardButton(text="⬅️ Menu",     callback_data="main_menu"),
    )
    return builder.as_markup()


# ─── Entry point ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_docs")
async def cb_docs_menu(cq: CallbackQuery):
    lang = await _get_lang()
    try:
        docs = await docs_api.list(lang=lang)
    except Exception as e:
        await cq.answer(f"Error: {e}", show_alert=True)
        return

    header = "📚 <b>Документация</b>" if lang == "ru" else "📚 <b>Documentation</b>"
    hint   = "Выберите тему:" if lang == "ru" else "Select a topic:"
    await cq.message.edit_text(
        f"{header}\n\n{hint}",
        reply_markup=_kb_doc_list(docs, lang),
        parse_mode="HTML",
    )


# ─── Open doc / navigate pages ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("docs_open_"))
async def cb_docs_page(cq: CallbackQuery):
    # callback pattern: docs_open_{doc_id}_{page}
    parts = cq.data.split("_", 3)   # ["docs", "open", doc_id, page]
    doc_id = parts[2]
    page = int(parts[3])

    lang = await _get_lang()
    try:
        content = await docs_api.get(doc_id, lang=lang)
    except Exception as e:
        await cq.answer(f"Error: {e}", show_alert=True)
        return

    chunks = _split_md(content)
    total = len(chunks)
    page = max(0, min(page, total - 1))
    text = chunks[page]

    header = f"📄 {page + 1}/{total}\n\n"
    try:
        await cq.message.edit_text(
            header + text,
            reply_markup=_kb_page(doc_id, page, total),
            parse_mode=None,
        )
    except Exception:
        await cq.answer()
        return
    await cq.answer()
