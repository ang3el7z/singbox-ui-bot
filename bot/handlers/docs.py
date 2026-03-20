"""
Documentation browser for the Telegram bot.
Supports Markdown-like formatting and disables link previews.
"""
from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.api_client import docs_api, settings_api

try:
    from aiogram.types import LinkPreviewOptions
except Exception:  # pragma: no cover
    LinkPreviewOptions = None

router = Router()

# Keep headroom under Telegram's 4096-char limit.
_CHUNK = 3600

_RE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_RE_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_RE_HEADER = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_RE_UL = re.compile(r"^\s*[-*]\s+(.+)$")
_RE_OL = re.compile(r"^\s*(\d+)\.\s+(.+)$")
_RE_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_RE_CODE_FENCE = re.compile(r"^\s*```")


def _t(lang: str, ru: str, en: str) -> str:
    return ru if lang == "ru" else en


async def _get_lang() -> str:
    try:
        result = await settings_api.get("bot_lang")
        value = result.get("value", "ru") if isinstance(result, dict) else "ru"
        return "en" if value == "en" else "ru"
    except Exception:
        return "ru"


def _render_inline(text: str) -> str:
    placeholders: dict[str, str] = {}
    counter = 0

    def put(value: str) -> str:
        nonlocal counter
        token = f"@@DOC_TOKEN_{counter}@@"
        counter += 1
        placeholders[token] = value
        return token

    def sub_link(match: re.Match[str]) -> str:
        label = html.escape(match.group(1))
        url = html.escape(match.group(2), quote=True)
        return put(f'<a href="{url}">{label}</a>')

    def sub_code(match: re.Match[str]) -> str:
        code = html.escape(match.group(1))
        return put(f"<code>{code}</code>")

    text = _RE_LINK.sub(sub_link, text)
    text = _RE_INLINE_CODE.sub(sub_code, text)
    escaped = html.escape(text)
    escaped = _RE_BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _RE_ITALIC.sub(r"<i>\1</i>", escaped)

    for token, value in placeholders.items():
        escaped = escaped.replace(token, value)
    return escaped


def _flush_paragraph(paragraph: list[str], blocks: list[str]) -> None:
    if not paragraph:
        return
    joined = " ".join(item.strip() for item in paragraph if item.strip())
    if joined:
        blocks.append(_render_inline(joined))
    paragraph.clear()


def _md_to_html_blocks(markdown_text: str) -> list[str]:
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    in_code = False
    code_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip("\n")

        if _RE_CODE_FENCE.match(line):
            if in_code:
                code = html.escape("\n".join(code_lines))
                blocks.append(f"<pre><code>{code}</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                _flush_paragraph(paragraph, blocks)
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not line.strip():
            _flush_paragraph(paragraph, blocks)
            continue

        if line.strip() == "---":
            _flush_paragraph(paragraph, blocks)
            blocks.append("--------")
            continue

        header = _RE_HEADER.match(line)
        if header:
            _flush_paragraph(paragraph, blocks)
            blocks.append(f"<b>{_render_inline(header.group(2))}</b>")
            continue

        ul = _RE_UL.match(line)
        if ul:
            _flush_paragraph(paragraph, blocks)
            blocks.append(f"- {_render_inline(ul.group(1))}")
            continue

        ol = _RE_OL.match(line)
        if ol:
            _flush_paragraph(paragraph, blocks)
            blocks.append(f"{ol.group(1)}. {_render_inline(ol.group(2))}")
            continue

        quote = _RE_QUOTE.match(line)
        if quote:
            _flush_paragraph(paragraph, blocks)
            quote_text = quote.group(1).strip()
            if quote_text:
                blocks.append(f"> {_render_inline(quote_text)}")
            continue

        # Markdown table rows: keep as monospace lines in Telegram.
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            _flush_paragraph(paragraph, blocks)
            blocks.append(f"<code>{html.escape(stripped)}</code>")
            continue

        paragraph.append(line)

    _flush_paragraph(paragraph, blocks)
    if in_code:
        code = html.escape("\n".join(code_lines))
        blocks.append(f"<pre><code>{code}</code></pre>")

    return blocks or ["<i>(empty)</i>"]


def _split_blocks(blocks: list[str]) -> list[str]:
    chunks: list[str] = []
    current = ""

    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= _CHUNK:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(block) <= _CHUNK:
            current = block
            continue

        # Split oversized code block safely.
        if block.startswith("<pre><code>") and block.endswith("</code></pre>"):
            open_tag = "<pre><code>"
            close_tag = "</code></pre>"
            code = block[len(open_tag) : -len(close_tag)]
            step = max(500, _CHUNK - len(open_tag) - len(close_tag))
            while code:
                part = code[:step]
                code = code[step:]
                chunks.append(f"{open_tag}{part}{close_tag}")
            continue

        # Fallback for extra long non-code block.
        rest = block
        while len(rest) > _CHUNK:
            chunks.append(rest[:_CHUNK])
            rest = rest[_CHUNK:]
        current = rest

    if current:
        chunks.append(current)

    return chunks or ["<i>(empty)</i>"]


def _kb_doc_list(docs: list[dict], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in docs:
        builder.row(
            InlineKeyboardButton(
                text=item["title"],
                callback_data=f"docs_open_{item['id']}_0",
            )
        )
    builder.row(
        InlineKeyboardButton(text=_t(lang, "Назад", "Back"), callback_data="main_menu")
    )
    return builder.as_markup()


def _kb_page(doc_id: str, page: int, total: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text=_t(lang, "Назад", "Prev"),
                callback_data=f"docs_open_{doc_id}_{page - 1}",
            )
        )
    if page < total - 1:
        nav.append(
            InlineKeyboardButton(
                text=_t(lang, "Далее", "Next"),
                callback_data=f"docs_open_{doc_id}_{page + 1}",
            )
        )
    if nav:
        builder.row(*nav)
    builder.row(
        InlineKeyboardButton(text=_t(lang, "Все статьи", "All docs"), callback_data="menu_docs"),
        InlineKeyboardButton(text=_t(lang, "Меню", "Menu"), callback_data="main_menu"),
    )
    return builder.as_markup()


async def _edit_text_no_preview(
    cq: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    kwargs = {
        "text": text,
        "reply_markup": reply_markup,
        "parse_mode": "HTML",
    }
    if LinkPreviewOptions is not None:
        try:
            await cq.message.edit_text(
                **kwargs,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            return
        except TypeError:
            pass
    await cq.message.edit_text(
        **kwargs,
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "menu_docs")
async def cb_docs_menu(cq: CallbackQuery):
    lang = await _get_lang()
    try:
        docs = await docs_api.list(lang=lang)
    except Exception as exc:
        await cq.answer(f"Error: {exc}", show_alert=True)
        return

    header = _t(lang, "<b>Документация</b>", "<b>Documentation</b>")
    hint = _t(lang, "Выберите тему:", "Select a topic:")
    await _edit_text_no_preview(
        cq,
        f"{header}\n\n{hint}",
        _kb_doc_list(docs, lang),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("docs_open_"))
async def cb_docs_page(cq: CallbackQuery):
    # callback pattern: docs_open_{doc_id}_{page}
    payload = cq.data[len("docs_open_") :]
    try:
        doc_id, page_text = payload.rsplit("_", 1)
        page = int(page_text)
    except Exception:
        await cq.answer("Invalid docs item", show_alert=True)
        return

    lang = await _get_lang()

    try:
        markdown_content = await docs_api.get(doc_id, lang=lang)
    except Exception as exc:
        await cq.answer(f"Error: {exc}", show_alert=True)
        return

    blocks = _md_to_html_blocks(markdown_content)
    chunks = _split_blocks(blocks)
    total = len(chunks)
    page = max(0, min(page, total - 1))

    title = _t(lang, "<b>Документация</b>", "<b>Documentation</b>")
    body = chunks[page]
    text = f"{title} • {page + 1}/{total}\n\n{body}"

    await _edit_text_no_preview(
        cq,
        text,
        _kb_page(doc_id, page, total, lang),
    )
    await cq.answer()
