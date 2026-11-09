"""Document Administration Service (multi-file upload 1..20 <= 50MB, SHA-256 duplicate check, metadata patch, version update, retry, removal) (T054)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.auth import Group
from app.db.models.document import (
    Document,
    DocumentGroup,
    DocumentLanguage,
    DocumentStatus,
    DocumentVersion,
    DocumentVersionStatus,
)
from app.documents.ingestion_job import derive_document_display_status, ingest_document_version
from app.documents.parser import DocumentParseError, detect_mime_type
from app.ops.observability import AppError
from app.ports.providers import BlobStore, Embedder


def _validate_dates(effective_from: date | None, expires_on: date | None) -> None:
    if effective_from is not None and expires_on is not None and expires_on <= effective_from:
        raise AppError(
            400,
            "invalid_dates",
            "Ngày hết hạn phải lớn hơn ngày hiệu lực (expires_on MUST > effective_from).",
        )


async def list_documents_admin(
    session: AsyncSession,
    *,
    status_filter: str | None = None,
    group_id: uuid.UUID | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    docs = list(
        (await session.execute(select(Document).order_by(Document.created_at.desc())))
        .scalars()
        .all()
    )
    q_norm = q.strip().lower() if q else ""
    items: list[dict[str, Any]] = []

    for doc in docs:
        if q_norm and q_norm not in doc.title.lower():
            continue
        groups = list(
            (
                await session.execute(
                    select(Group)
                    .join(DocumentGroup, DocumentGroup.group_id == Group.id)
                    .where(DocumentGroup.document_id == doc.id, Group.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        if group_id and not any(g.id == group_id for g in groups):
            continue

        versions = list(
            (
                await session.execute(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == doc.id)
                    .order_by(DocumentVersion.version_number.asc())
                )
            )
            .scalars()
            .all()
        )
        derived = derive_document_display_status(doc, versions)
        if status_filter and derived["display_status"] != status_filter:
            continue

        is_orphaned = (not doc.is_company_wide) and (len(groups) == 0) and (
            doc.status == DocumentStatus.active
        )
        items.append(
            {
                "id": str(doc.id),
                "title": doc.title,
                "is_company_wide": doc.is_company_wide,
                "effective_from": doc.effective_from.isoformat() if doc.effective_from else None,
                "expires_on": doc.expires_on.isoformat() if doc.expires_on else None,
                "current_version_id": (
                    str(doc.current_version_id) if doc.current_version_id else None
                ),
                "status": doc.status.value,
                "display_status": derived["display_status"],
                "latest_error_code": derived["latest_error_code"],
                "latest_error_detail": derived["latest_error_detail"],
                "is_orphaned": is_orphaned,
                "groups": [{"id": str(g.id), "name": g.name} for g in groups],
                "version_count": len(versions),
            }
        )
    return items


async def get_document_admin_detail(
    session: AsyncSession, *, document_id: uuid.UUID
) -> dict[str, Any]:
    doc = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        raise AppError(404, "document_not_found", "Không tìm thấy tài liệu.")

    groups = list(
        (
            await session.execute(
                select(Group)
                .join(DocumentGroup, DocumentGroup.group_id == Group.id)
                .where(DocumentGroup.document_id == doc.id, Group.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    versions = list(
        (
            await session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == doc.id)
                .order_by(DocumentVersion.version_number.asc())
            )
        )
        .scalars()
        .all()
    )
    derived = derive_document_display_status(doc, versions)
    return {
        "id": str(doc.id),
        "title": doc.title,
        "is_company_wide": doc.is_company_wide,
        "effective_from": doc.effective_from.isoformat() if doc.effective_from else None,
        "expires_on": doc.expires_on.isoformat() if doc.expires_on else None,
        "current_version_id": str(doc.current_version_id) if doc.current_version_id else None,
        "status": doc.status.value,
        "display_status": derived["display_status"],
        "groups": [{"id": str(g.id), "name": g.name} for g in groups],
        "versions": [
            {
                "id": str(v.id),
                "version_number": v.version_number,
                "original_filename": v.original_filename,
                "mime_type": v.mime_type,
                "size_bytes": v.size_bytes,
                "sha256": v.sha256,
                "language": v.language.value,
                "page_count": v.page_count,
                "token_count": v.token_count,
                "status": v.status.value,
                "error_code": v.error_code,
                "error_detail": v.error_detail,
                "created_at": v.created_at.isoformat(),
                "processed_at": v.processed_at.isoformat() if v.processed_at else None,
            }
            for v in versions
        ],
    }


async def upload_documents_admin(
    session: AsyncSession,
    *,
    uploaded_by: uuid.UUID,
    files: list[tuple[str, bytes]],
    group_ids: list[uuid.UUID],
    is_company_wide: bool,
    effective_from: date | None = None,
    expires_on: date | None = None,
    custom_title: str | None = None,
    blob_store: BlobStore,
    embedder: Embedder,
    run_inline: bool = True,
) -> list[dict[str, Any]]:
    settings = get_settings()
    if not files or len(files) > settings.max_upload_files_count:
        raise AppError(
            400,
            "invalid_files_count",
            f"Số lượng file tải lên mỗi lần phải từ 1 đến {settings.max_upload_files_count}.",
        )
    _validate_dates(effective_from, expires_on)

    for fname, raw_bytes in files:
        if len(raw_bytes) > settings.max_upload_file_bytes:
            raise AppError(
                400,
                "too_large",
                f"File '{fname}' vượt quá dung lượng tối đa 50 MB.",
            )

    created: list[dict[str, Any]] = []
    for fname, raw_bytes in files:
        title = (custom_title if (custom_title and len(files) == 1) else Path(fname).stem).strip()
        doc = Document(
            title=title or fname,
            is_company_wide=is_company_wide,
            effective_from=effective_from,
            expires_on=expires_on,
            status=DocumentStatus.active,
            created_by=uploaded_by,
        )
        session.add(doc)
        await session.flush()

        for gid in set(group_ids):
            session.add(DocumentGroup(document_id=doc.id, group_id=gid))

        try:
            mime_type = detect_mime_type(fname, raw_bytes)
        except DocumentParseError as parse_err:
            mime_type = "application/octet-stream"
            sha = hashlib.sha256(raw_bytes).hexdigest()
            blob_key = f"versions/{doc.id}/v1/{fname}"
            await blob_store.put(blob_key, raw_bytes, mime_type)
            ver = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                original_filename=fname,
                mime_type=mime_type,
                size_bytes=len(raw_bytes),
                sha256=sha,
                blob_key=blob_key,
                language=DocumentLanguage.vi,
                status=DocumentVersionStatus.failed,
                error_code=parse_err.error_code,
                error_detail=parse_err.detail,
                uploaded_by=uploaded_by,
            )
            session.add(ver)
            await session.commit()
            created.append(
                {
                    "document_id": str(doc.id),
                    "title": doc.title,
                    "version_id": str(ver.id),
                    "version_number": 1,
                    "status": ver.status.value,
                    "error_code": ver.error_code,
                    "error_detail": ver.error_detail,
                }
            )
            continue

        sha = hashlib.sha256(raw_bytes).hexdigest()
        blob_key = f"versions/{doc.id}/v1/{fname}"
        await blob_store.put(blob_key, raw_bytes, mime_type)

        ver = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            original_filename=fname,
            mime_type=mime_type,
            size_bytes=len(raw_bytes),
            sha256=sha,
            blob_key=blob_key,
            language=DocumentLanguage.vi,
            status=DocumentVersionStatus.queued,
            uploaded_by=uploaded_by,
        )
        session.add(ver)
        await session.commit()

        if run_inline:
            ver = await ingest_document_version(
                session, version_id=ver.id, blob_store=blob_store, embedder=embedder
            )

        created.append(
            {
                "document_id": str(doc.id),
                "title": doc.title,
                "version_id": str(ver.id),
                "version_number": 1,
                "status": ver.status.value,
                "error_code": ver.error_code,
                "error_detail": ver.error_detail,
            }
        )

    return created


async def upload_new_version_admin(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    filename: str,
    raw_bytes: bytes,
    blob_store: BlobStore,
    embedder: Embedder,
    run_inline: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    if len(raw_bytes) > settings.max_upload_file_bytes:
        raise AppError(400, "too_large", "Dung lượng file vượt quá 50 MB.")

    doc = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        raise AppError(404, "document_not_found", "Không tìm thấy tài liệu.")

    sha = hashlib.sha256(raw_bytes).hexdigest()
    if doc.current_version_id is not None:
        cur_ver = (
            await session.execute(
                select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
            )
        ).scalar_one_or_none()
        if cur_ver is not None and cur_ver.sha256 == sha:
            raise AppError(
                409,
                "duplicate_version",
                "File tải lên trùng hệt (SHA-256) với phiên bản hiện hành của tài liệu.",
            )

    max_v = (
        await session.execute(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == doc.id
            )
        )
    ).scalar_one()
    next_v = int(max_v or 0) + 1

    try:
        mime_type = detect_mime_type(filename, raw_bytes)
    except DocumentParseError as parse_err:
        mime_type = "application/octet-stream"
        blob_key = f"versions/{doc.id}/v{next_v}/{filename}"
        await blob_store.put(blob_key, raw_bytes, mime_type)
        ver = DocumentVersion(
            document_id=doc.id,
            version_number=next_v,
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=len(raw_bytes),
            sha256=sha,
            blob_key=blob_key,
            language=DocumentLanguage.vi,
            status=DocumentVersionStatus.failed,
            error_code=parse_err.error_code,
            error_detail=parse_err.detail,
            uploaded_by=uploaded_by,
        )
        session.add(ver)
        await session.commit()
        return {
            "document_id": str(doc.id),
            "version_id": str(ver.id),
            "version_number": next_v,
            "status": ver.status.value,
            "error_code": ver.error_code,
            "error_detail": ver.error_detail,
        }

    blob_key = f"versions/{doc.id}/v{next_v}/{filename}"
    await blob_store.put(blob_key, raw_bytes, mime_type)
    ver = DocumentVersion(
        document_id=doc.id,
        version_number=next_v,
        original_filename=filename,
        mime_type=mime_type,
        size_bytes=len(raw_bytes),
        sha256=sha,
        blob_key=blob_key,
        language=DocumentLanguage.vi,
        status=DocumentVersionStatus.queued,
        uploaded_by=uploaded_by,
    )
    session.add(ver)
    await session.commit()

    if run_inline:
        ver = await ingest_document_version(
            session, version_id=ver.id, blob_store=blob_store, embedder=embedder
        )

    return {
        "document_id": str(doc.id),
        "version_id": str(ver.id),
        "version_number": next_v,
        "status": ver.status.value,
        "error_code": ver.error_code,
        "error_detail": ver.error_detail,
    }


async def update_document_metadata_admin(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    title: str | None = None,
    group_ids: list[uuid.UUID] | None = None,
    is_company_wide: bool | None = None,
    effective_from: date | None = None,
    expires_on: date | None = None,
    update_effective_from: bool = False,
    update_expires_on: bool = False,
) -> dict[str, Any]:
    doc = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        raise AppError(404, "document_not_found", "Không tìm thấy tài liệu.")

    new_eff = effective_from if update_effective_from else doc.effective_from
    new_exp = expires_on if update_expires_on else doc.expires_on
    _validate_dates(new_eff, new_exp)

    if title is not None and title.strip():
        doc.title = title.strip()
    if is_company_wide is not None:
        doc.is_company_wide = is_company_wide
    if update_effective_from:
        doc.effective_from = effective_from
    if update_expires_on:
        doc.expires_on = expires_on

    if group_ids is not None:
        await session.execute(
            delete(DocumentGroup).where(DocumentGroup.document_id == doc.id)
        )
        for gid in set(group_ids):
            session.add(DocumentGroup(document_id=doc.id, group_id=gid))

    await session.commit()
    return await get_document_admin_detail(session, document_id=doc.id)


async def retry_document_version_admin(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    blob_store: BlobStore,
    embedder: Embedder,
) -> dict[str, Any]:
    ver = (
        await session.execute(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.document_id == document_id,
            )
        )
    ).scalar_one_or_none()
    if ver is None:
        raise AppError(404, "version_not_found", "Không tìm thấy phiên bản tài liệu.")
    if ver.status != DocumentVersionStatus.failed:
        raise AppError(400, "version_not_failed", "Chỉ có thể thử lại phiên bản đang ở trạng thái lỗi.")

    ver.status = DocumentVersionStatus.queued
    await session.commit()
    ver = await ingest_document_version(
        session, version_id=ver.id, blob_store=blob_store, embedder=embedder
    )
    return {
        "document_id": str(document_id),
        "version_id": str(ver.id),
        "status": ver.status.value,
        "error_code": ver.error_code,
        "error_detail": ver.error_detail,
    }


async def remove_document_admin(
    session: AsyncSession, *, document_id: uuid.UUID
) -> None:
    doc = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        raise AppError(404, "document_not_found", "Không tìm thấy tài liệu.")
    doc.status = DocumentStatus.removed
    await session.commit()
