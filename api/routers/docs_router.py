"""
Serves the internal documentation files (docs/*.md) via REST API.
Both the Telegram bot and Web UI use this endpoint to display docs.
"""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from api.deps import require_any_auth
from fastapi import Depends

router = APIRouter()

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"

DOC_META = {
    "overview":   {"title": "📖 Overview / Обзор",          "file": "OVERVIEW.md"},
    "install":    {"title": "🚀 Install / Установка",        "file": "INSTALL.md"},
    "api":        {"title": "🔌 API Reference",              "file": "API.md"},
    "federation": {"title": "🔗 Federation / Федерация",     "file": "FEDERATION.md"},
    "webui":      {"title": "🌐 Web UI",                     "file": "WEB_UI.md"},
}


@router.get("/", summary="List available documentation files")
async def list_docs(_=Depends(require_any_auth)):
    return [
        {"id": doc_id, "title": meta["title"], "file": meta["file"]}
        for doc_id, meta in DOC_META.items()
    ]


@router.get("/{doc_id}", response_class=PlainTextResponse, summary="Get documentation file content")
async def get_doc(doc_id: str, _=Depends(require_any_auth)):
    meta = DOC_META.get(doc_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Doc '{doc_id}' not found")
    path = DOCS_DIR / meta["file"]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File {meta['file']} not found on disk")
    return path.read_text(encoding="utf-8")
