"""Conversation, Turn, Citation, TurnTrace, and Feedback SQLAlchemy models (T027, T057)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
     Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, EncryptedText, JsonData, StringArray, utcnow
from app.db.models.auth import PreferredLanguage


class TurnKind(enum.StrEnum):
    answer = "answer"
    clarification = "clarification"
    refusal_not_found = "refusal_not_found"
    refusal_unsupported = "refusal_unsupported"
    refusal_out_of_scope = "refusal_out_of_scope"
    partial_answer = "partial_answer"
    error = "error"


class FeedbackRating(enum.StrEnum):
    helpful = "helpful"
    not_helpful = "not_helpful"


class Conversation(Base):
    """conversations table per data-model.md (T027)."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "pending_clarification_count >= 0 AND pending_clarification_count <= 2",
            name="ck_conversations_clarification_count",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text(), nullable=False)
    scope_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    pending_clarification_count: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class Turn(Base):
    """turns table per data-model.md (T027)."""

    __tablename__ = "turns"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer(), nullable=False)
    question: Mapped[str] = mapped_column(EncryptedText(), nullable=False)
    kind: Mapped[TurnKind] = mapped_column(
        Enum(TurnKind, name="turn_kind"), default=TurnKind.answer, nullable=False
    )
    answer_language: Mapped[PreferredLanguage] = mapped_column(
        Enum(PreferredLanguage, name="preferred_language"),
        default=PreferredLanguage.vi,
        nullable=False,
    )
    answer: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    clarification_options: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JsonData(), nullable=True
    )
    assumptions: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    missing_parts: Mapped[list[str]] = mapped_column(StringArray(), default=list, nullable=False)
    limit_reached: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    scope_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    latency_ms: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    ttft_ms: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)


class Citation(Base):
    """citations table per data-model.md (T027)."""

    __tablename__ = "citations"
    __table_args__ = (CheckConstraint("marker >= 1", name="ck_citations_marker_positive"),)

    turn_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("turns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marker: Mapped[int] = mapped_column(Integer(), nullable=False)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    document_title: Mapped[str] = mapped_column(Text(), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer(), default=1, nullable=False)
    section_path: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date(), nullable=True)
    snippet: Mapped[str] = mapped_column(Text(), default="", nullable=False)


class TurnTrace(Base):
    """turn_traces table per data-model.md (T027)."""

    __tablename__ = "turn_traces"

    turn_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("turns.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonData(), nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 5), default=Decimal("0.00000"), nullable=False)


class Feedback(Base):
    """feedback table per data-model.md (T057)."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("comment IS NULL OR length(comment) <= 2000", name="ck_feedback_comment_len"),
    )

    turn_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("turns.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        Enum(FeedbackRating, name="feedback_rating"), nullable=False
    )
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)
