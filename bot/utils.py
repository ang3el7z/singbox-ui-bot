"""Utility helpers for the bot."""
import io
import qrcode
from aiogram.types import BufferedInputFile


def format_bytes(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def format_uptime(seconds: int) -> str:
    """Format seconds into human-readable uptime string."""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def make_qr(data: str, filename: str = "qr.png") -> BufferedInputFile:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename=filename)


def truncate(text: str, max_len: int = 4000) -> str:
    if len(text) <= max_len:
        return text
    from api.routers.settings_router import get_runtime
    suffix = "\n... (обрезано)" if get_runtime("bot_lang", "ru") == "ru" else "\n... (truncated)"
    return text[:max_len] + suffix
