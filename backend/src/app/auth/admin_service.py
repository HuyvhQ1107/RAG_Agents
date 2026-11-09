"""User & Group Administration Service with orphan document detection (T041, FR-016, FR-016a, FR-019)."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import hash_password
from app.db.base import utcnow
from app.db.models.auth import (
    VALID_ROLES,
    Group,
    PreferredLanguage,
    SessionRecord,
    User,
    UserGroup,
    UserStatus,
)
from app.db.models.document import Document, DocumentGroup, DocumentStatus
from app.ops.observability import AppError


def _generate_temporary_password() -> str:
    return f"Tmp-{secrets.token_urlsafe(10)}!9"


def _normalize_roles(roles: list[str] | None) -> list[str]:
    clean = {r.strip() for r in (roles or ["employee"]) if r.strip()}
    invalid = clean - VALID_ROLES
    if invalid:
        raise AppError(400, "invalid_roles", f"Vai trò không hợp lệ: {', '.join(sorted(invalid))}")
    clean.add("employee")
    return sorted(clean)


async def list_users_admin(
    session: AsyncSession,
    *,
    q: str | None = None,
    group_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(User).order_by(User.username.asc())
    if status:
        stmt = stmt.where(User.status == UserStatus(status))
    users = list((await session.execute(stmt)).scalars().all())
    q_norm = q.strip().lower() if q else ""

    items: list[dict[str, Any]] = []
    for u in users:
        if q_norm and q_norm not in u.username.lower() and q_norm not in u.display_name.lower():
            continue
        g_stmt = (
            select(Group)
            .join(UserGroup, UserGroup.group_id == Group.id)
            .where(UserGroup.user_id == u.id, Group.deleted_at.is_(None))
        )
        groups = list((await session.execute(g_stmt)).scalars().all())
        if group_id and not any(g.id == group_id for g in groups):
            continue
        items.append(
            {
                "id": str(u.id),
                "username": u.username,
                "display_name": u.display_name,
                "email": u.email,
                "roles": list(u.roles),
                "status": u.status.value,
                "must_change_password": u.must_change_password,
                "groups": [{"id": str(g.id), "name": g.name} for g in groups],
            }
        )
    return items


async def create_user_admin(
    session: AsyncSession,
    *,
    username: str,
    display_name: str,
    email: str | None = None,
    roles: list[str] | None = None,
    group_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    uname = username.strip()
    if len(uname) < 3 or len(uname) > 64:
        raise AppError(400, "invalid_username", "Tên đăng nhập phải từ 3 đến 64 ký tự.")

    exists_user = (
        await session.execute(select(User).where(func.lower(User.username) == uname.lower()))
    ).scalar_one_or_none()
    if exists_user is not None:
        raise AppError(409, "username_exists", "Tên đăng nhập đã tồn tại.")

    temp_password = _generate_temporary_password()
    user = User(
        username=uname,
        display_name=display_name.strip(),
        email=email.strip() if email else None,
        password_hash=hash_password(temp_password),
        must_change_password=True,
        roles=_normalize_roles(roles),
        status=UserStatus.active,
        preferred_language=PreferredLanguage.vi,
    )
    session.add(user)
    await session.flush()

    for gid in set(group_ids or []):
        grp = (
            await session.execute(
                select(Group).where(Group.id == gid, Group.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if grp is None:
            raise AppError(404, "group_not_found", f"Không tìm thấy phòng ban: {gid}")
        session.add(UserGroup(user_id=user.id, group_id=grp.id))

    await session.commit()
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "roles": list(user.roles),
        "status": user.status.value,
        "temporary_password": temp_password,
    }


async def update_user_admin(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    display_name: str | None = None,
    email: str | None = None,
    roles: list[str] | None = None,
    group_ids: list[uuid.UUID] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise AppError(404, "user_not_found", "Không tìm thấy người dùng.")

    if display_name is not None:
        user.display_name = display_name.strip()
    if email is not None:
        user.email = email.strip() or None
    if roles is not None:
        user.roles = _normalize_roles(roles)

    invalidate_sessions = False
    if status is not None:
        new_status = UserStatus(status)
        if new_status != UserStatus.active:
            invalidate_sessions = True
        else:
            user.failed_login_count = 0
            user.locked_until = None
        user.status = new_status

    if group_ids is not None:
        await session.execute(delete(UserGroup).where(UserGroup.user_id == user.id))
        for gid in set(group_ids):
            grp = (
                await session.execute(
                    select(Group).where(Group.id == gid, Group.deleted_at.is_(None))
                )
            ).scalar_one_or_none()
            if grp is None:
                raise AppError(404, "group_not_found", f"Không tìm thấy phòng ban: {gid}")
            session.add(UserGroup(user_id=user.id, group_id=grp.id))

    if invalidate_sessions:
        await session.execute(delete(SessionRecord).where(SessionRecord.user_id == user.id))

    await session.commit()
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "roles": list(user.roles),
        "status": user.status.value,
    }


async def reset_user_password_admin(
    session: AsyncSession, *, user_id: uuid.UUID
) -> dict[str, Any]:
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise AppError(404, "user_not_found", "Không tìm thấy người dùng.")

    temp_password = _generate_temporary_password()
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    if user.status == UserStatus.locked:
        user.status = UserStatus.active

    await session.execute(delete(SessionRecord).where(SessionRecord.user_id == user.id))
    await session.commit()
    return {
        "id": str(user.id),
        "username": user.username,
        "temporary_password": temp_password,
        "must_change_password": True,
    }


async def list_groups_admin(session: AsyncSession) -> list[dict[str, Any]]:
    groups = list(
        (
            await session.execute(
                select(Group).where(Group.deleted_at.is_(None)).order_by(Group.name.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(g.id),
            "name": g.name,
            "description": g.description,
        }
        for g in groups
    ]


async def create_group_admin(
    session: AsyncSession, *, name: str, description: str | None = None
) -> dict[str, Any]:
    clean_name = name.strip()
    if not clean_name:
        raise AppError(400, "invalid_group_name", "Tên phòng ban không được để trống.")
    existing = (
        await session.execute(select(Group).where(func.lower(Group.name) == clean_name.lower()))
    ).scalar_one_or_none()
    if existing is not None and existing.deleted_at is None:
        raise AppError(409, "group_exists", "Phòng ban đã tồn tại.")
    if existing is not None and existing.deleted_at is not None:
        existing.deleted_at = None
        existing.description = description
        await session.commit()
        return {"id": str(existing.id), "name": existing.name, "description": existing.description}

    grp = Group(name=clean_name, description=description)
    session.add(grp)
    await session.commit()
    return {"id": str(grp.id), "name": grp.name, "description": grp.description}


async def update_group_admin(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    grp = (
        await session.execute(
            select(Group).where(Group.id == group_id, Group.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if grp is None:
        raise AppError(404, "group_not_found", "Không tìm thấy phòng ban.")
    if name is not None and name.strip():
        grp.name = name.strip()
    if description is not None:
        grp.description = description
    await session.commit()
    return {"id": str(grp.id), "name": grp.name, "description": grp.description}


async def soft_delete_group_admin(
    session: AsyncSession, *, group_id: uuid.UUID
) -> dict[str, Any]:
    """
    Soft-delete a group per FR-016a & data-model.md:
    - Documents belonging ONLY to this deleted group become inaccessible to non-admins
      (NEVER become company-wide).
    - Returns orphaned_document_ids so the admin UI can warn the administrator.
    """
    grp = (
        await session.execute(
            select(Group).where(Group.id == group_id, Group.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if grp is None:
        raise AppError(404, "group_not_found", "Không tìm thấy phòng ban.")

    grp.deleted_at = utcnow()
    await session.flush()

    # Find active, non-company-wide documents linked to this group that now have 0 active groups
    doc_ids = list(
        (
            await session.execute(
                select(Document.id)
                .join(DocumentGroup, DocumentGroup.document_id == Document.id)
                .where(
                    DocumentGroup.group_id == grp.id,
                    Document.status == DocumentStatus.active,
                    Document.is_company_wide.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )

    orphaned: list[str] = []
    for did in doc_ids:
        remaining_active = (
            await session.execute(
                select(func.count())
                .select_from(DocumentGroup)
                .join(Group, Group.id == DocumentGroup.group_id)
                .where(
                    DocumentGroup.document_id == did,
                    Group.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        if int(remaining_active) == 0:
            orphaned.append(str(did))

    await session.commit()
    return {"orphaned_document_ids": orphaned}
