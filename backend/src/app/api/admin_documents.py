"""Admin Document endpoints (/api/v1/admin/documents/*) per contracts/api.md (T054)."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.db.base import get_db_session
from app.db.models.auth import User
from app.documents.admin_service import (
    get_document_admin_detail,
    list_documents_admin,
    remove_document_admin,
    retry_document_version_admin,
    update_document_metadata_admin,
    upload_documents_admin,
    upload_new_version_admin,
)
from app.ports.providers import BlobStore, Embedder

router = APIRouter(prefix="/api/v1/admin/documents", tags=["admin-documents"])


def get_blob_store(request: Request) -> BlobStore:
    return request.app.state.blob_store  # type: ignore[no-any-return]


def get_embedder(request: Request) -> Embedder:
    return request.app.state.embedder  # type: ignore[no-any-return]


class PatchDocumentRequest(BaseModel):
    title: str | None = None
    group_ids: list[uuid.UUID] | None = None
    is_company_wide: bool | None = None
    effective_from: date | None = None
    expires_on: date | None = None


@router.get("")
async def get_admin_documents(
    status: str | None = None,
    group_id: uuid.UUID | None = None,
    q: str | None = None,
    _admin: User = Depends(require_roles("content_admin", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    items = await list_documents_admin(
        session, status_filter=status, group_id=group_id, q=q
    )
    return {"items": items, "next_cursor": None}


@router.post("", status_code=202)
async def post_admin_documents(
    files: list[UploadFile] = File(...),
    metadata: str = Form(default="{}"),
    user: User = Depends(require_roles("content_admin", "admin")),
    session: AsyncSession = Depends(get_db_session),
    blob_store: BlobStore = Depends(get_blob_store),
    embedder: Embedder = Depends(get_embedder),
) -> dict[str, Any]:
    meta = json.loads(metadata or "{}")
    group_ids = [uuid.UUID(str(gid)) for gid in meta.get("group_ids", [])]
    is_company_wide = bool(meta.get("is_company_wide", False))
    eff = date.fromisoformat(meta["effective_from"]) if meta.get("effective_from") else None
    exp = date.fromisoformat(meta["expires_on"]) if meta.get("expires_on") else None
    custom_title = meta.get("title")

    file_tuples: list[tuple[str, bytes]] = []
    for f in files:
        raw = await f.read()
        file_tuples.append((f.filename or "document.pdf", raw))

    created = await upload_documents_admin(
        session,
        uploaded_by=user.id,
        files=file_tuples,
        group_ids=group_ids,
        is_company_wide=is_company_wide,
        effective_from=eff,
        expires_on=exp,
        custom_title=custom_title,
        blob_store=blob_store,
        embedder=embedder,
        run_inline=True,
    )
    return {"items": created}


@router.get("/{document_id}")
async def get_admin_document(
    document_id: uuid.UUID,
    _admin: User = Depends(require_roles("content_admin", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await get_document_admin_detail(session, document_id=document_id)


@router.patch("/{document_id}")
async def patch_admin_document(
    document_id: uuid.UUID,
    payload: PatchDocumentRequest,
    _admin: User = Depends(require_roles("content_admin", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    fields_set = payload.model_fields_set
    return await update_document_metadata_admin(
        session,
        document_id=document_id,
        title=payload.title,
        group_ids=payload.group_ids,
        is_company_wide=payload.is_company_wide,
        effective_from=payload.effective_from,
        expires_on=payload.expires_on,
        update_effective_from="effective_from" in fields_set,
        update_expires_on="expires_on" in fields_set,
    )


@router.post("/{document_id}/versions", status_code=202)
async def post_admin_document_version(
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(require_roles("content_admin", "admin")),
    session: AsyncSession = Depends(get_db_session),
    blob_store: BlobStore = Depends(get_blob_store),
    embedder: Embedder = Depends(get_embedder),
) -> dict[str, Any]:
    raw = await file.read()
    return await upload_new_version_admin(
        session,
        document_id=document_id,
        uploaded_by=user.id,
        filename=file.filename or "document.pdf",
        raw_bytes=raw,
        blob_store=blob_store,
        embedder=embedder,
        run_inline=True,
    )


@router.post("/{document_id}/versions/{version_id}/retry")
async def post_retry_document_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    _admin: User = Depends(require_roles("content_admin", "admin")),
    session: AsyncSession = Depends(get_db_session),
    blob_store: BlobStore = Depends(get_blob_store),
    embedder: Embedder = Depends(get_embedder),
) -> dict[str, Any]:
    return await retry_document_version_admin(
        session,
        document_id=document_id,
        version_id=version_id,
        blob_store=blob_store,
        embedder=embedder,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_admin_document(
    document_id: uuid.UUID,
    response: Response,
    _admin: User = Depends(require_roles("content_admin", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await remove_document_admin(session, document_id=document_id)
    response.status_code = 204
    return response
