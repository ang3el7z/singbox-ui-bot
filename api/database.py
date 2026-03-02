from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, Text, Float, func
from datetime import datetime
from typing import Optional

DATABASE_URL = "sqlite+aiosqlite:///data/app.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ─── Web UI user (for JWT login) ──────────────────────────────────────────────

class WebUser(Base):
    __tablename__ = "web_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ─── Telegram admins ──────────────────────────────────────────────────────────

class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ─── VPN Clients ──────────────────────────────────────────────────────────────

class Client(Base):
    """
    Metadata for VPN clients.
    Credentials (uuid/password) live in sing-box config.json → inbounds[].users.
    This table stores limits, expiry, sub URLs, and traffic counters.
    """
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    inbound_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)  # vless, trojan, ss, etc.

    # Credentials (mirrored in config.json)
    uuid: Mapped[Optional[str]] = mapped_column(String(64))      # VLESS / VMess / TUIC
    password: Mapped[Optional[str]] = mapped_column(String(128)) # Trojan / Shadowsocks / Hysteria2

    # Subscription
    sub_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    # Limits
    total_gb: Mapped[float] = mapped_column(Float, default=0.0)   # 0 = unlimited
    expiry_time: Mapped[Optional[int]] = mapped_column(BigInteger) # unix ms, null = no limit
    enable: Mapped[bool] = mapped_column(Boolean, default=True)

    # Traffic counters (updated periodically from sing-box)
    upload: Mapped[int] = mapped_column(BigInteger, default=0)
    download: Mapped[int] = mapped_column(BigInteger, default=0)

    # Meta
    tg_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


# ─── Inbounds ─────────────────────────────────────────────────────────────────

class Inbound(Base):
    """
    Inbound metadata — mirrors an entry in sing-box config.json inbounds[].
    The full config dict is stored as JSON in config_json for flexibility.
    """
    __tablename__ = "inbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    listen_port: Mapped[int] = mapped_column(Integer, nullable=False)
    enable: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)   # full inbound dict as JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ─── Audit Log ────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)  # "tg:123456" or "web:admin"
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ─── Federation nodes ─────────────────────────────────────────────────────────

class FederationNode(Base):
    __tablename__ = "federation_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String(256), nullable=False)
    secret: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_ping: Mapped[Optional[datetime]] = mapped_column(DateTime)
    role: Mapped[str] = mapped_column(String(16), default="node")   # node | bridge
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ─── App settings ─────────────────────────────────────────────────────────────

class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


# ─── DB init ──────────────────────────────────────────────────────────────────

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
