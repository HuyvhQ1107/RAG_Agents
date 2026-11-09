"""User-facing document search, citation detail, and source file download endpoints (T035)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.base import get_db_session
from app.db.models.auth import User
from app.db.models.conversation import Citation
from app.db.models.document import Chunk, Document, DocumentVersion
from app.ops.observability import AppError
from app.ports.providers import BlobStore
from app.rag.access_filter import (
    build_accessible_documents_predicate,
    verify_user_can_access_document,
)

router = APIRouter(prefix="/api/v1", tags=["documents"])


def get_blob_store(request: Request) -> BlobStore:
    return request.app.state.blob_store  # type: ignore[no-any-return]


@router.get("/documents/search")
async def search_permitted_documents(
    q: str = Query(default="", max_length=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    stmt = (
        select(Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
        .where(build_accessible_documents_predicate(user_id=user.id))
        .order_by(Document.title.asc())
    )
    rows = (await session.execute(stmt)).all()
    q_norm = q.strip().lower()
    items: list[dict[str, Any]] = []
    for doc, ver in rows:
        if q_norm and q_norm not in doc.title.lower():
            continue
        items.append(
            {
                "id": str(doc.id),
                "title": doc.title,
                "effective_from": doc.effective_from.isoformat() if doc.effective_from else None,
                "expires_on": doc.expires_on.isoformat() if doc.expires_on else None,
                "language": ver.language.value,
            }
        )
    return items[:25]


@router.get("/citations/{citation_id}")
async def get_citation_detail(
    citation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    cit = (
        await session.execute(select(Citation).where(Citation.id == citation_id))
    ).scalar_one_or_none()
    if cit is None:
        raise AppError(404, "citation_not_found", "Không tìm thấy trích dẫn.")

    # Re-verify user's current permission on the referenced document (FR-018, FR-019)
    doc = await verify_user_can_access_document(session, user.id, cit.document_id)
    if doc is None:
        raise AppError(404, "citation_not_found", "Không tìm thấy trích dẫn.")

    chunk = (
        await session.execute(select(Chunk).where(Chunk.id == cit.chunk_id))
    ).scalar_one_or_none()

    return {
        "citation_id": str(cit.id),
        "marker": cit.marker,
        "document_id": str(cit.document_id),
        "document_version_id": str(cit.document_version_id),
        "document_title": cit.document_title,
        "version_number": cit.version_number,
        "section_path": cit.section_path,
        "page_start": cit.page_start,
        "page_end": cit.page_end,
        "effective_from": cit.effective_from.isoformat() if cit.effective_from else None,
        "snippet": cit.snippet,
        "full_content": chunk.content if chunk else cit.snippet,
    }


@router.get("/documents/{document_id}/file")
async def download_document_file(
    document_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    blob_store: BlobStore = Depends(get_blob_store),
) -> Response:
    doc = await verify_user_can_access_document(session, user.id, document_id)
    if doc is None:
        raise AppError(404, "document_not_found", "Không tìm thấy tài liệu.")

    target_vid = version_id or doc.current_version_id
    if target_vid is None:
        raise AppError(404, "version_not_found", "Tài liệu chưa có phiên bản sẵn sàng.")

    ver = (
        await session.execute(
            select(DocumentVersion).where(
                DocumentVersion.id == target_vid, DocumentVersion.document_id == doc.id
            )
        )
    ).scalar_one_or_none()
    if ver is None:
        raise AppError(404, "version_not_found", "Không tìm thấy phiên bản tài liệu.")

    try:
        raw_bytes = await blob_store.get(ver.blob_key)
    except FileNotFoundError as exc:
        raise AppError(404, "file_not_found", "Không tìm thấy file gốc.") from exc

    return Response(
        content=raw_bytes,
        media_type=ver.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{ver.original_filename}"',
        },
    )
