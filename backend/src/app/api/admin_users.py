"""Admin User & Group endpoints (/api/v1/admin/users, /api/v1/admin/groups) per contracts/api.md (T042)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_service import (
    create_group_admin,
    create_user_admin,
    list_groups_admin,
    list_users_admin,
    reset_user_password_admin,
    soft_delete_group_admin,
    update_group_admin,
    update_user_admin,
)
from app.auth.dependencies import require_roles
from app.db.base import get_db_session
from app.db.models.auth import User

router = APIRouter(prefix="/api/v1/admin", tags=["admin-users"])


class CreateUserRequest(BaseModel):
    username: str
    display_name: str
    email: str | None = None
    roles: list[str] = ["employee"]
    group_ids: list[uuid.UUID] = []


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    email: str | None = None
    roles: list[str] | None = None
    group_ids: list[uuid.UUID] | None = None
    status: str | None = None


class CreateGroupRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateGroupRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.get("/users")
async def get_users(
    q: str | None = None,
    group_id: uuid.UUID | None = None,
    status: str | None = None,
    _admin: User = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    items = await list_users_admin(session, q=q, group_id=group_id, status=status)
    return {"items": items, "next_cursor": None}


@router.post("/users", status_code=201)
async def post_user(
    payload: CreateUserRequest,
    _admin: User = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await create_user_admin(
        session,
        username=payload.username,
        display_name=payload.display_name,
        email=payload.email,
        roles=payload.roles,
        group_ids=payload.group_ids,
    )


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    _admin: User = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await update_user_admin(
        session,
        user_id=user_id,
        display_name=payload.display_name,
        email=payload.email,
        roles=payload.roles,
        group_ids=payload.group_ids,
        status=payload.status,
    )


@router.post("/users/{user_id}/reset-password")
async def post_reset_password(
    user_id: uuid.UUID,
    _admin: User = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await reset_user_password_admin(session, user_id=user_id)


@router.get("/groups")
async def get_groups(
    _user: User = Depends(require_roles("admin", "content_admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    items = await list_groups_admin(session)
    return {"items": items}


@router.post("/groups", status_code=201)
async def post_group(
    payload: CreateGroupRequest,
    _admin: User = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await create_group_admin(session, name=payload.name, description=payload.description)


@router.patch("/groups/{group_id}")
async def patch_group(
    group_id: uuid.UUID,
    payload: UpdateGroupRequest,
    _admin: User = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await update_group_admin(
        session,
        group_id=group_id,
        name=payload.name,
        description=payload.description,
    )


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: uuid.UUID,
    _admin: User = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await soft_delete_group_admin(session, group_id=group_id)
