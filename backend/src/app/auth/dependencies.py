"""FastAPI authentication and RBAC dependencies (T013)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import get_user_by_session_token
from app.config import get_settings
from app.db.base import get_db_session
from app.db.models.auth import User
from app.ops.observability import AppError


async def get_current_user_allow_password_change(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> User:
    settings = get_settings()
    raw_token = request.cookies.get(settings.session_cookie_name, "")
    found = await get_user_by_session_token(session, raw_token)
    if found is None:
        raise AppError(401, "unauthenticated", "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    user, sess_rec = found
    request.state.session_token_hash = sess_rec.token_hash
    return user


async def get_current_user(
    request: Request,
    user: User = Depends(get_current_user_allow_password_change),
) -> User:
    if user.must_change_password and not request.url.path.startswith("/api/v1/auth"):
        raise AppError(
            403,
            "password_change_required",
            "Bạn cần đổi mật khẩu tạm thời trước khi sử dụng hệ thống.",
        )
    return user


def require_roles(*required: str) -> Callable[..., Any]:
    async def _dep(user: User = Depends(get_current_user)) -> User:
        user_roles = set(user.roles or [])
        if "admin" in user_roles:
            return user
        if not (user_roles & set(required)):
            # Return 404 or 403? Spec says unauthorized resources return 404; role check for admin routes:
            raise AppError(404, "not_found", "Không tìm thấy tài nguyên.")
        return user

    return _dep
