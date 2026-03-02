"""
Documentation browser for the Telegram bot.
Fetches markdown files from the API and sends them in readable chunks.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.api_client import docs_api

router = Router()

# Maximum Telegram message length
_CHUNK = 3800


def _split_md(text: str) -> list[str]:
    """
    Split markdown text into Telegram-safe chunks.
    Tries to break at paragraph boundaries (double newlines).
    """
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = (current + "\n\n" + block).lstrip() if current else block
        if len(candidate) <= _CHUNK:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            # Block itself might be too long — hard split
            while len(block) > _CHUNK:
                chunks.append(block[:_CHUNK])
                block = block[_CHUNK:]
            current = block
    if current.strip():
        chunks.append(current.strip())
    return chunks or ["(empty)"]


def _kb_doc_list(docs: list) -> InlineKeyboardMarkup:
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
    try:
        docs = await docs_api.list()
    except Exception as e:
        await cq.answer(f"Error: {e}", show_alert=True)
        return
    await cq.message.edit_text(
        "📚 <b>Documentation</b>\n\nSelect a topic:",
        reply_markup=_kb_doc_list(docs),
        parse_mode="HTML",
    )


# ─── Open doc / navigate pages ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("docs_open_"))
async def cb_docs_page(cq: CallbackQuery):
    # callback pattern: docs_open_{doc_id}_{page}
    parts = cq.data.split("_", 3)   # ["docs", "open", doc_id, page]
    doc_id = parts[2]
    page = int(parts[3])

    try:
        content = await docs_api.get(doc_id)
    except Exception as e:
        await cq.answer(f"Error: {e}", show_alert=True)
        return

    chunks = _split_md(content)
    total = len(chunks)
    page = max(0, min(page, total - 1))
    text = chunks[page]

    header = f"📄 Page {page + 1}/{total}\n\n"
    # Send as plain text (no HTML parse — markdown headers use # which is fine)
    try:
        await cq.message.edit_text(
            header + text,
            reply_markup=_kb_page(doc_id, page, total),
            parse_mode=None,
        )
    except Exception:
        # Message unchanged — just close the loading spinner
        await cq.answer()
        return
    await cq.answer()
