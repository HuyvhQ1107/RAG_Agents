"""Authentication endpoints (/api/v1/auth/*) per contracts/api.md (T014)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user_allow_password_change
from app.auth.service import (
    authenticate_user,
    change_user_password,
    get_user_active_groups,
    logout_session,
)
from app.config import get_settings
from app.db.base import get_db_session
from app.db.models.auth import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login", status_code=204)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    settings = get_settings()
    _, raw_token = await authenticate_user(
        session=session,
        username=payload.username,
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    response.status_code = 204
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.session_sliding_hours * 3600,
        path="/",
    )
    return response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    _user: User = Depends(get_current_user_allow_password_change),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    settings = get_settings()
    raw_token = request.cookies.get(settings.session_cookie_name, "")
    await logout_session(session, raw_token)
    response.status_code = 204
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/me")
async def me(
    user: User = Depends(get_current_user_allow_password_change),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    groups = await get_user_active_groups(session, user.id)
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "roles": list(user.roles),
        "groups": [{"id": str(g.id), "name": g.name} for g in groups],
        "must_change_password": user.must_change_password,
        "preferred_language": user.preferred_language.value,
    }


@router.post("/change-password", status_code=204)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user_allow_password_change),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    keep_hash = getattr(request.state, "session_token_hash", None)
    await change_user_password(
        session=session,
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        keep_token_hash=keep_hash,
    )
    response.status_code = 204
    return response
