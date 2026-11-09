"""Liveness (/healthz) and Readiness (/readyz) endpoints (T064)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_db_session)) -> dict[str, object]:
    await session.execute(text("SELECT 1"))
    settings = get_settings()
    return {
        "status": "ready",
        "llm_fast_model": settings.llm_fast_model,
        "llm_answer_model": settings.llm_answer_model,
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
    }
