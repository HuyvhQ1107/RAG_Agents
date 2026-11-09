"""Ingestion job & periodic maintenance jobs (atomic version switch, expiry, superseded cleanup, 90-day purge) (T053, T063)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models.conversation import Conversation
from app.db.models.document import (
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionStatus,
)
from app.documents.chunker import chunk_parsed_document
from app.documents.parser import DocumentParseError, parse_document_bytes
from app.ports.providers import BlobStore, Embedder
from app.privacy.masker import mask_pii


async def ingest_document_version(
    session: AsyncSession,
    *,
    version_id: uuid.UUID,
    blob_store: BlobStore,
    embedder: Embedder,
) -> DocumentVersion:
    """
    Parse -> Structural Chunk -> PII Mask -> Batch Embed (gemini-embedding-001 768d) ->
    Atomically promote version to `ready`, set `documents.current_version_id`,
    and mark the previous current version `superseded` (FR-024, FR-025).
    """
    ver = (
        await session.execute(select(DocumentVersion).where(DocumentVersion.id == version_id))
    ).scalar_one_or_none()
    if ver is None:
        raise ValueError(f"DocumentVersion not found: {version_id}")

    doc = (
        await session.execute(select(Document).where(Document.id == ver.document_id))
    ).scalar_one()

    ver.status = DocumentVersionStatus.processing
    ver.error_code = None
    ver.error_detail = None
    await session.flush()

    try:
        raw_bytes = await blob_store.get(ver.blob_key)
        mime_type, parsed = parse_document_bytes(ver.original_filename, raw_bytes)
        structural_chunks = chunk_parsed_document(parsed)
        if not structural_chunks:
            raise DocumentParseError("empty_document", "Không trích xuất được đoạn nội dung nào.")

        # Mask PII before sending to embedding provider (Constitution III, FR-020)
        masked_contents: list[str] = []
        contextual_inputs: list[str] = []
        for sc in structural_chunks:
            masked_text, _ = mask_pii(sc.content)
            masked_contents.append(masked_text)
            contextual_inputs.append(f"{doc.title} — {sc.section_path}: {masked_text}")

        vectors = await embedder.embed_documents(contextual_inputs)

        # Clear any old chunks belonging to this same version (in case of retry)
        await session.execute(delete(Chunk).where(Chunk.document_version_id == ver.id))

        total_tokens = 0
        for sc, masked_text, vec in zip(structural_chunks, masked_contents, vectors, strict=True):
            total_tokens += sc.token_count
            session.add(
                Chunk(
                    document_version_id=ver.id,
                    document_id=doc.id,
                    ordinal=sc.ordinal,
                    section_path=sc.section_path,
                    page_start=sc.page_start,
                    page_end=sc.page_end,
                    content=sc.content,
                    content_masked=masked_text,
                    kind=sc.kind,
                    token_count=sc.token_count,
                    embedding=vec,
                    tsv=f"{doc.title} {sc.section_path} {masked_text}".lower(),
                )
            )

        # Atomic version promotion in the same transaction:
        if doc.current_version_id and doc.current_version_id != ver.id:
            prev_ver = (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
                )
            ).scalar_one_or_none()
            if prev_ver is not None:
                prev_ver.status = DocumentVersionStatus.superseded

        ver.mime_type = mime_type
        ver.language = parsed.language
        ver.page_count = parsed.page_count
        ver.token_count = total_tokens
        ver.status = DocumentVersionStatus.ready
        ver.processed_at = utcnow()
        doc.current_version_id = ver.id

        await session.commit()
        return ver

    except DocumentParseError as parse_err:
        ver.status = DocumentVersionStatus.failed
        ver.error_code = parse_err.error_code
        ver.error_detail = parse_err.detail
        await session.commit()
        return ver
    except Exception as exc:
        ver.status = DocumentVersionStatus.failed
        ver.error_code = "parse_error"
        ver.error_detail = str(exc)
        await session.commit()
        return ver


async def cleanup_superseded_chunks(session: AsyncSession, retention_days: int = 30) -> int:
    """Remove chunks of superseded document versions older than 30 days."""
    cutoff = utcnow() - timedelta(days=retention_days)
    old_versions = list(
        (
            await session.execute(
                select(DocumentVersion.id).where(
                    DocumentVersion.status == DocumentVersionStatus.superseded,
                    DocumentVersion.updated_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if not old_versions:
        return 0
    res = await session.execute(
        delete(Chunk).where(Chunk.document_version_id.in_(old_versions))
    )
    await session.commit()
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


async def purge_old_conversations(session: AsyncSession, retention_days: int = 90) -> int:
    """Delete conversations (and cascading turns/citations/traces) inactive for > 90 days (T063)."""
    cutoff = utcnow() - timedelta(days=retention_days)
    res = await session.execute(
        delete(Conversation).where(Conversation.last_activity_at < cutoff)
    )
    await session.commit()
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


def derive_document_display_status(
    doc: Document,
    versions: list[DocumentVersion],
) -> dict[str, Any]:
    """
    Compute derived display status per data-model.md:
    removed > processing > failed > expired > scheduled > active
    """
    from datetime import date

    today = date.today()
    latest = versions[-1] if versions else None
    if doc.status.value == "removed":
        disp = "removed"
    elif doc.current_version_id is None and any(
        v.status in (DocumentVersionStatus.queued, DocumentVersionStatus.processing)
        for v in versions
    ):
        disp = "processing"
    elif doc.current_version_id is None and latest and latest.status == DocumentVersionStatus.failed:
        disp = "failed"
    elif doc.expires_on is not None and doc.expires_on < today:
        disp = "expired"
    elif doc.effective_from is not None and doc.effective_from > today:
        disp = "scheduled"
    else:
        disp = "active"

    return {
        "display_status": disp,
        "latest_error_code": latest.error_code if latest else None,
        "latest_error_detail": latest.error_detail if latest else None,
    }
