"""Auth, User, Group, and Session SQLAlchemy models (T010)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CIText, StringArray, utcnow

VALID_ROLES = {"employee", "content_admin", "operator", "admin"}


class UserStatus(enum.StrEnum):
    active = "active"
    locked = "locked"
    disabled = "disabled"


class PreferredLanguage(enum.StrEnum):
    vi = "vi"
    en = "en"


class User(Base):
    """users table per data-model.md."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(username) >= 3 AND length(username) <= 64", name="ck_users_username_len"),
    )

    username: Mapped[str] = mapped_column(CIText(), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(Text(), nullable=False)
    email: Mapped[str | None] = mapped_column(CIText(), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text(), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    roles: Mapped[list[str]] = mapped_column(
        StringArray(), default=lambda: ["employee"], nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status"), default=UserStatus.active, nullable=False
    )
    failed_login_count: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(32), default="local", nullable=False)
    preferred_language: Mapped[PreferredLanguage] = mapped_column(
        Enum(PreferredLanguage, name="preferred_language"),
        default=PreferredLanguage.vi,
        nullable=False,
    )


class Group(Base):
    """groups (phòng ban/nhóm) table per data-model.md."""

    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(Text(), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserGroup(Base):
    """user_groups composite association table per data-model.md."""

    __tablename__ = "user_groups"

    id: Mapped[uuid.UUID | None] = None  # type: ignore[assignment]
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )


class SessionRecord(Base):
    """sessions table per data-model.md."""

    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    user_agent: Mapped[str | None] = mapped_column(Text(), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
