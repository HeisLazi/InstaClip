"""SQLAlchemy foundation for InstaClip public edition (blueprint Phase 1).

Local-first: SQLite at data/instaclip.db now, swappable to another DB later via
HEISLAZI_DATABASE_URL. Every creator-owned row carries `creator_id` so a future
multi-creator migration does not require rebuilding the data model.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from config import paths

DEFAULT_CREATOR_ID = "default"

_DB_URL = os.environ.get("HEISLAZI_DATABASE_URL") or f"sqlite:///{paths.DATA_DIR / 'instaclip.db'}"

engine = create_engine(
    _DB_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if _DB_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[float] = mapped_column(default=time.time)
    updated_at: Mapped[float] = mapped_column(default=time.time, onupdate=time.time)


class TenantMixin:
    """Every creator-owned row is scoped by creator_id (tenant-ready)."""
    creator_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_CREATOR_ID, index=True)
