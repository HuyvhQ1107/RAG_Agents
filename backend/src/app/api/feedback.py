"""Feedback endpoint (PUT /api/v1/turns/{turn_id}/feedback) per contracts/api.md (T058)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.base import get_db_session
from app.db.models.auth import User
from app.ops.service import upsert_turn_feedback

router = APIRouter(prefix="/api/v1/turns", tags=["feedback"])


class PutFeedbackRequest(BaseModel):
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = Field(default=None, max_length=2000)


@router.put("/{turn_id}/feedback")
async def put_feedback(
    turn_id: uuid.UUID,
    payload: PutFeedbackRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await upsert_turn_feedback(
        session,
        user_id=user.id,
        turn_id=turn_id,
        rating=payload.rating,
        comment=payload.comment,
    )
