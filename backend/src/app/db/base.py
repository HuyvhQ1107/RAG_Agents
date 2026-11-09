"""SQLAlchemy 2.0 async base, custom dialect-aware types, and session factory (T009)."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import DateTime, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings


def uuid7() -> uuid.UUID:
    """Generate a time-ordered UUIDv7 (RFC 9562)."""
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b
    return uuid.UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(UTC)


class CIText(TypeDecorator[str]):
    """Case-insensitive text: uses CITEXT on PostgreSQL and lower-collation String elsewhere."""

    impl = String(255)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import CITEXT

            return dialect.type_descriptor(CITEXT())
        return dialect.type_descriptor(String(255))

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return value.strip()


class StringArray(TypeDecorator[list[str]]):
    """Text[] on PostgreSQL, JSON string list on SQLite."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Text()))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[str] | None, dialect: Any) -> Any:
        if value is None:
            return [] if dialect.name == "postgresql" else "[]"
        if dialect.name == "postgresql":
            return list(value)
        return json.dumps(list(value), ensure_ascii=False)

    def process_result_value(self, value: Any, dialect: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value]
        return [str(x) for x in json.loads(value)]


class JsonData(TypeDecorator[Any]):
    """JSONB on PostgreSQL, JSON text on SQLite."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)


class EmbeddingVector(TypeDecorator[list[float]]):
    """pgvector vector(dim) on PostgreSQL, JSON float list on SQLite."""

    impl = Text
    cache_ok = True

    def __init__(self, dim: int = 768) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [float(x) for x in value]
        return json.dumps([float(x) for x in value])

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(x) for x in value]
        if hasattr(value, "tolist"):
            return [float(x) for x in value.tolist()]
        return [float(x) for x in json.loads(value)]


class EncryptedText(TypeDecorator[str]):
    """Fernet column-level encryption using FIELD_ENCRYPTION_KEY (for turns.question)."""

    impl = Text
    cache_ok = True

    def _fernet(self) -> Fernet:
        key = get_settings().field_encryption_key.encode("utf-8")
        return Fernet(key)

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        token = self._fernet().encrypt(value.encode("utf-8"))
        return token.decode("ascii")

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        try:
            return self._fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except Exception:
            return value


class Base(DeclarativeBase):
    """Declarative base with UUIDv7 id and UTC created_at / updated_at."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        if settings.database_url.startswith("sqlite"):
            _engine = create_async_engine(
                settings.database_url,
                connect_args={"timeout": 30},
                future=True,
            )
        else:
            _engine = create_async_engine(settings.database_url, future=True)
    return _engine


def set_engine(engine: AsyncEngine) -> None:
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
