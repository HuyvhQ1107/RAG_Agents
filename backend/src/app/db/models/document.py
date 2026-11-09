"""Document, DocumentGroup, DocumentVersion, and Chunk SQLAlchemy models (T011)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, EmbeddingVector

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/html",
    "text/markdown",
}

ALLOWED_ERROR_CODES = {
    "scanned_pdf_unsupported",
    "encrypted_unsupported",
    "unsupported_format",
    "empty_document",
    "parse_error",
    "too_large",
}


class DocumentStatus(enum.StrEnum):
    active = "active"
    removed = "removed"


class DocumentLanguage(enum.StrEnum):
    vi = "vi"
    en = "en"
    mixed = "mixed"


class DocumentVersionStatus(enum.StrEnum):
    queued = "queued"
    processing = "processing"
    ready = "ready"
    failed = "failed"
    superseded = "superseded"


class ChunkKind(enum.StrEnum):
    text = "text"
    table = "table"


class Document(Base):
    """documents table per data-model.md."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "expires_on IS NULL OR effective_from IS NULL OR expires_on > effective_from",
            name="ck_documents_expires_after_effective",
        ),
    )

    title: Mapped[str] = mapped_column(Text(), nullable=False, index=True)
    is_company_wide: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date(), nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date(), nullable=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", use_alter=True, name="fk_documents_current_version"),
        nullable=True,
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.active,
        nullable=False,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)


class DocumentGroup(Base):
    """document_groups composite association table per data-model.md."""

    __tablename__ = "document_groups"

    id: Mapped[uuid.UUID | None] = None  # type: ignore[assignment]
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )


class DocumentVersion(Base):
    """document_versions table per data-model.md."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_doc_version_number"),
        CheckConstraint("size_bytes <= 52428800", name="ck_doc_version_size_50mb"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    original_filename: Mapped[str] = mapped_column(Text(), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    blob_key: Mapped[str] = mapped_column(Text(), nullable=False)
    language: Mapped[DocumentLanguage] = mapped_column(
        Enum(DocumentLanguage, name="document_language"),
        default=DocumentLanguage.vi,
        nullable=False,
    )
    page_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    status: Mapped[DocumentVersionStatus] = mapped_column(
        Enum(DocumentVersionStatus, name="document_version_status"),
        default=DocumentVersionStatus.queued,
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text(), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Chunk(Base):
    """chunks table per data-model.md."""

    __tablename__ = "chunks"

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer(), nullable=False)
    section_path: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    content_masked: Mapped[str] = mapped_column(Text(), nullable=False)
    kind: Mapped[ChunkKind] = mapped_column(
        Enum(ChunkKind, name="chunk_kind"), default=ChunkKind.text, nullable=False
    )
    token_count: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingVector(768), nullable=True)
    tsv: Mapped[str | None] = mapped_column(Text(), nullable=True)
