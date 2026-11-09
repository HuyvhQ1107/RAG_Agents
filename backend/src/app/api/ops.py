"""Operator endpoints (/api/v1/ops/*) per contracts/api.md (T058)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.db.base import get_db_session
from app.db.models.auth import User
from app.ops.service import (
    get_ops_metrics_summary,
    get_ops_turn_trace,
    list_ops_feedback,
)

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


@router.get("/metrics/summary")
async def get_metrics_summary(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    _op: User = Depends(require_roles("operator", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await get_ops_metrics_summary(session, from_dt=from_dt, to_dt=to_dt)


@router.get("/feedback")
async def get_feedback_list(
    rating: str | None = None,
    _op: User = Depends(require_roles("operator", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    items = await list_ops_feedback(session, rating=rating)
    return {"items": items, "next_cursor": None}


@router.get("/turns/{turn_id}/trace")
async def get_turn_trace(
    turn_id: uuid.UUID,
    _op: User = Depends(require_roles("operator", "admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await get_ops_turn_trace(session, turn_id=turn_id)
