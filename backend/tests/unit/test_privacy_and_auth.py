"""Unit tests for Vietnamese PII masking/unmasking and Argon2id/session lockout rules (T023)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.service import authenticate_user, change_user_password, hash_password
from app.db.base import Base
from app.db.models.auth import PreferredLanguage, User, UserStatus
from app.ops.observability import AppError
from app.privacy.masker import contains_raw_pii, mask_pii


def test_vietnamese_pii_masking_and_reversible_unmasking() -> None:
    raw = (
        "Nhân viên Nguyễn Văn A có CCCD 079099001234, SĐT 0912345678, "
        "email nguyenvana@gmail.com, số tài khoản: 19034567890123 và mức lương 35.000.000 VNĐ."
    )
    assert contains_raw_pii(raw) is True

    masked, session = mask_pii(raw)
    assert "079099001234" not in masked
    assert "0912345678" not in masked
    assert "nguyenvana@gmail.com" not in masked
    assert "19034567890123" not in masked
    assert "35.000.000" not in masked
    assert "<CCCD_1>" in masked
    assert "<PHONE_1>" in masked
    assert "<EMAIL_1>" in masked
    assert "<BANK_ACCOUNT_1>" in masked
    assert "<SALARY_1>" in masked
    assert contains_raw_pii(masked) is False

    # Reversibility within request scope
    llm_answer = "Thông tin liên hệ của bạn là <PHONE_1> và CCCD <CCCD_1> [1]."
    restored = session.unmask(llm_answer)
    assert "0912345678" in restored
    assert "079099001234" in restored


@pytest.mark.asyncio
async def test_argon2id_auth_and_5_strike_account_lockout() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        user = User(
            username="tester",
            display_name="Tester",
            password_hash=hash_password("CorrectHorseBatteryStaple1!"),
            must_change_password=True,
            roles=["employee"],
            status=UserStatus.active,
            preferred_language=PreferredLanguage.vi,
        )
        session.add(user)
        await session.commit()

        # 4 failed attempts return 401
        for _ in range(4):
            with pytest.raises(AppError) as exc_info:
                await authenticate_user(session, "tester", "WrongPassword")
            assert exc_info.value.status_code == 401
            assert exc_info.value.code == "invalid_credentials"

        # 5th failed attempt locks account and returns 423
        with pytest.raises(AppError) as exc_info:
            await authenticate_user(session, "tester", "WrongPassword")
        assert exc_info.value.status_code == 423
        assert exc_info.value.code == "account_locked"

        # Even correct password fails with 423 while locked
        with pytest.raises(AppError) as exc_info:
            await authenticate_user(session, "tester", "CorrectHorseBatteryStaple1!")
        assert exc_info.value.status_code == 423

        # Unlock and test password change enforcement (>= 12 chars)
        user.status = UserStatus.active
        user.locked_until = None
        user.failed_login_count = 0
        await session.commit()

        authed_user, token = await authenticate_user(
            session, "tester", "CorrectHorseBatteryStaple1!"
        )
        assert token
        assert authed_user.must_change_password is True

        with pytest.raises(AppError) as exc_info:
            await change_user_password(
                session, authed_user, "CorrectHorseBatteryStaple1!", "short"
            )
        assert exc_info.value.code == "weak_password"

        await change_user_password(
            session, authed_user, "CorrectHorseBatteryStaple1!", "NewStrongPassword123!"
        )
        assert authed_user.must_change_password is False

    await engine.dispose()
