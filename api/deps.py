"""
FastAPI dependencies for authentication.

Two auth strategies:
  1. JWT Bearer — Web UI users (WebUser model)
  2. X-Internal-Token — Telegram bot (shared secret, no DB lookup needed)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.config import settings
from api.database import get_db, WebUser, AuditLog, async_session

ALGORITHM = "HS256"
bearer_scheme = HTTPBearer(auto_error=False)


# ─── Password hashing ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ─── JWT ──────────────────────────────────────────────────────────────────────

def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ─── Dependencies ─────────────────────────────────────────────────────────────

async def get_current_web_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> WebUser:
    """Validate JWT Bearer token → return WebUser."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    username = decode_token(credentials.credentials)
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(
        select(WebUser).where(WebUser.username == username, WebUser.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def require_internal(x_internal_token: str = Header(default="")) -> bool:
    """Validate X-Internal-Token for bot → api calls."""
    if x_internal_token != settings.internal_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token")
    return True


async def require_any_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_internal_token: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Accept either JWT (web UI) or X-Internal-Token (bot).
    Returns {"actor": "web:username"} or {"actor": "bot"}.
    """
    if x_internal_token and x_internal_token == settings.internal_token:
        return {"actor": "bot"}
    if credentials:
        username = decode_token(credentials.credentials)
        if username:
            result = await db.execute(
                select(WebUser).where(WebUser.username == username, WebUser.is_active == True)
            )
            user = result.scalar_one_or_none()
            if user:
                return {"actor": f"web:{username}"}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


# ─── Audit helper ─────────────────────────────────────────────────────────────

async def audit(actor: str, action: str, details: str = None) -> None:
    async with async_session() as session:
        session.add(AuditLog(actor=actor, action=action, details=details))
        await session.commit()
