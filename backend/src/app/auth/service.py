"""Argon2id password hashing, server-side session manager, and lockout rules (T013)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import utcnow
from app.db.models.auth import Group, SessionRecord, User, UserGroup, UserStatus
from app.ops.observability import AppError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def authenticate_user(
    session: AsyncSession,
    username: str,
    password: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, str]:
    settings = get_settings()
    stmt = select(User).where(func.lower(User.username) == username.strip().lower())
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise AppError(401, "invalid_credentials", "Tên đăng nhập hoặc mật khẩu không đúng.")

    now = utcnow()
    locked_until = _ensure_utc(user.locked_until)

    if user.status == UserStatus.disabled:
        raise AppError(401, "invalid_credentials", "Tài khoản đã bị vô hiệu hóa.")

    if user.status == UserStatus.locked or (locked_until is not None and locked_until > now):
        raise AppError(
            423,
            "account_locked",
            "Tài khoản đang bị khóa tạm thời do nhập sai mật khẩu quá số lần cho phép.",
        )

    # Clear expired lock if time has passed
    if locked_until is not None and locked_until <= now:
        user.locked_until = None
        user.failed_login_count = 0

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.status = UserStatus.locked
            await session.commit()
            raise AppError(
                423,
                "account_locked",
                "Tài khoản đã bị khóa do nhập sai mật khẩu 5 lần liên tiếp.",
            )
        await session.commit()
        raise AppError(401, "invalid_credentials", "Tên đăng nhập hoặc mật khẩu không đúng.")

    user.failed_login_count = 0
    user.locked_until = None
    if user.status == UserStatus.locked:
        user.status = UserStatus.active

    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(raw_token)
    expires_at = now + timedelta(hours=settings.session_sliding_hours)
    sess = SessionRecord(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        last_seen_at=now,
        user_agent=user_agent,
        ip=ip,
    )
    session.add(sess)
    await session.commit()
    return user, raw_token


async def get_user_by_session_token(
    session: AsyncSession, raw_token: str
) -> tuple[User, SessionRecord] | None:
    if not raw_token:
        return None
    settings = get_settings()
    token_hash = hash_session_token(raw_token)
    stmt = (
        select(User, SessionRecord)
        .join(SessionRecord, SessionRecord.user_id == User.id)
        .where(SessionRecord.token_hash == token_hash)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    user, sess_rec = row
    now = utcnow()
    expires_at = _ensure_utc(sess_rec.expires_at)
    if user.status != UserStatus.active or (expires_at is not None and expires_at <= now):
        await session.delete(sess_rec)
        await session.commit()
        return None

    # Sliding expiration
    sess_rec.last_seen_at = now
    sess_rec.expires_at = now + timedelta(hours=settings.session_sliding_hours)
    await session.commit()
    return user, sess_rec


async def logout_session(session: AsyncSession, raw_token: str) -> None:
    if not raw_token:
        return
    token_hash = hash_session_token(raw_token)
    await session.execute(delete(SessionRecord).where(SessionRecord.token_hash == token_hash))
    await session.commit()


async def change_user_password(
    session: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
    keep_token_hash: str | None = None,
) -> None:
    if len(new_password) < 12:
        raise AppError(400, "weak_password", "Mật khẩu mới phải có ít nhất 12 ký tự.")
    if not verify_password(current_password, user.password_hash):
        raise AppError(400, "invalid_current_password", "Mật khẩu hiện tại không đúng.")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False

    stmt = delete(SessionRecord).where(SessionRecord.user_id == user.id)
    if keep_token_hash:
        stmt = stmt.where(SessionRecord.token_hash != keep_token_hash)
    await session.execute(stmt)
    await session.commit()


async def get_user_active_groups(session: AsyncSession, user_id: uuid.UUID) -> list[Group]:
    stmt = (
        select(Group)
        .join(UserGroup, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == user_id, Group.deleted_at.is_(None))
        .order_by(Group.name)
    )
    return list((await session.execute(stmt)).scalars().all())
