"""Documentation API loaded from markdown files in docs/content/{ru,en}."""
from __future__ import annotations

from pathlib import Path
from typing import Final, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from api.deps import require_any_auth

router = APIRouter()


class DocMeta(TypedDict):
    id: str
    title: dict[str, str]


_DOCS_INDEX: Final[list[DocMeta]] = [
    {"id": "overview", "title": {"ru": "\u041e\u0431\u0437\u043e\u0440", "en": "Overview"}},
    {"id": "installation", "title": {"ru": "\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430", "en": "Installation"}},
    {"id": "quick-start", "title": {"ru": "\u0411\u044b\u0441\u0442\u0440\u044b\u0439 \u0441\u0442\u0430\u0440\u0442", "en": "Quick Start"}},
    {"id": "operations", "title": {"ru": "\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u0438", "en": "Operations"}},
    {"id": "troubleshooting", "title": {"ru": "\u0414\u0438\u0430\u0433\u043d\u043e\u0441\u0442\u0438\u043a\u0430", "en": "Troubleshooting"}},
    {"id": "maintenance", "title": {"ru": "\u041e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435", "en": "Maintenance"}},
    {"id": "federation", "title": {"ru": "\u0424\u0435\u0434\u0435\u0440\u0430\u0446\u0438\u044f", "en": "Federation"}},
    {"id": "faq", "title": {"ru": "FAQ", "en": "FAQ"}},
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS_ROOTS: Final[list[Path]] = [
    _REPO_ROOT / "docs" / "content",
    Path("/opt/singbox-ui-bot/docs/content"),
]
_WEB_DOCS_ROOTS: Final[list[Path]] = [
    _REPO_ROOT / "web" / "docs",
    Path("/opt/singbox-ui-bot/web/docs"),
]


def _first_existing(paths: list[Path]) -> Path:
    for candidate in paths:
        if candidate.exists():
            return candidate
    # Keep previous behavior when nothing exists: use primary path for clear errors.
    return paths[0]


def _lang(lang: str) -> str:
    return "en" if lang == "en" else "ru"


def _find_doc(doc_id: str) -> DocMeta:
    for item in _DOCS_INDEX:
        if item["id"] == doc_id:
            return item
    raise HTTPException(status_code=404, detail=f"Doc '{doc_id}' not found")


def _read_doc(doc_id: str, lang: str) -> str:
    _find_doc(doc_id)
    picked = _lang(lang)
    fallback_order = [picked, "ru", "en"]
    roots = _DOCS_ROOTS

    for root in roots:
        for code in fallback_order:
            path = root / code / f"{doc_id}.md"
            if path.exists():
                return path.read_text(encoding="utf-8").strip()

    raise HTTPException(
        status_code=404,
        detail=f"Content file for doc '{doc_id}' not found in docs/content/",
    )


def _list_docs(lang: str) -> list[dict[str, str]]:
    picked = _lang(lang)
    return [
        {"id": item["id"], "title": item["title"].get(picked, item["title"]["en"])}
        for item in _DOCS_INDEX
    ]


@router.get("/public", summary="List public documentation")
async def list_docs_public(lang: str = Query("ru", pattern="^(ru|en)$")):
    return _list_docs(lang)


@router.get("/public/{doc_id}", response_class=PlainTextResponse, summary="Get public doc content")
async def get_doc_public(doc_id: str, lang: str = Query("ru", pattern="^(ru|en)$")):
    return _read_doc(doc_id, lang)


@router.get("/site", response_class=HTMLResponse, summary="Standalone documentation page")
async def docs_site():
    page = _first_existing(_WEB_DOCS_ROOTS) / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Docs page not found")
    html = page.read_text(encoding="utf-8")
    html = html.replace("/web/docs/docs.css", "/api/docs/assets/docs.css")
    html = html.replace("/web/docs/docs.js", "/api/docs/assets/docs.js")
    return HTMLResponse(content=html)


@router.get("/assets/{asset_name}", summary="Standalone docs assets")
async def docs_site_asset(asset_name: str):
    allowed = {
        "docs.css": "text/css; charset=utf-8",
        "docs.js": "application/javascript; charset=utf-8",
    }
    if asset_name not in allowed:
        raise HTTPException(status_code=404, detail="Asset not found")

    path = _first_existing(_WEB_DOCS_ROOTS) / asset_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path, media_type=allowed[asset_name])


@router.get("/", summary="List available documentation")
async def list_docs(lang: str = Query("ru", pattern="^(ru|en)$"), _=Depends(require_any_auth)):
    return _list_docs(lang)


@router.get("/{doc_id}", response_class=PlainTextResponse, summary="Get doc content")
async def get_doc(doc_id: str, lang: str = Query("ru", pattern="^(ru|en)$"), _=Depends(require_any_auth)):
    return _read_doc(doc_id, lang)
