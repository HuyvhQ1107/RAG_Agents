"""Mandatory SQL access-control & document lifecycle pre-filter (T039, FR-018, FR-019, FR-025a, SC-005)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import Group, UserGroup
from app.db.models.document import (
    Document,
    DocumentGroup,
    DocumentStatus,
)


def build_accessible_documents_predicate(
    user_id: uuid.UUID,
    as_of_date: date | None = None,
    scope_document_id: uuid.UUID | None = None,
) -> Any:
    """
    Build SQL WHERE predicate enforcing:
    1. Document is active and has a ready current_version_id
    2. Document is not expired (expires_on IS NULL OR expires_on >= as_of_date)
    3. User has department access (is_company_wide OR active group intersection where group.deleted_at IS NULL)
    4. Optional single-document scope matches
    """
    today = as_of_date or date.today()

    group_access_exists = exists(
        select(1)
        .select_from(DocumentGroup)
        .join(Group, and_(Group.id == DocumentGroup.group_id, Group.deleted_at.is_(None)))
        .join(
            UserGroup,
            and_(
                UserGroup.group_id == DocumentGroup.group_id,
                UserGroup.user_id == user_id,
            ),
        )
        .where(DocumentGroup.document_id == Document.id)
    )

    conditions: list[Any] = [
        Document.status == DocumentStatus.active,
        Document.current_version_id.is_not(None),
        or_(Document.expires_on.is_(None), Document.expires_on >= today),
        or_(Document.is_company_wide.is_(True), group_access_exists),
    ]
    if scope_document_id is not None:
        conditions.append(Document.id == scope_document_id)

    return and_(*conditions)


def apply_document_access_filter(
    stmt: Select[Any],
    user_id: uuid.UUID,
    as_of_date: date | None = None,
    scope_document_id: uuid.UUID | None = None,
) -> Select[Any]:
    return stmt.where(
        build_accessible_documents_predicate(
            user_id=user_id,
            as_of_date=as_of_date,
            scope_document_id=scope_document_id,
        )
    )


async def verify_user_can_access_document(
    session: AsyncSession,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    as_of_date: date | None = None,
) -> Document | None:
    """Uncached DB permission check (FR-019). Returns None if unauthorized, removed, or expired."""
    stmt = select(Document).where(
        build_accessible_documents_predicate(
            user_id=user_id,
            as_of_date=as_of_date,
            scope_document_id=document_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()
