"""Feedback and Operator Metrics & Trace Inspection Service (T058, FR-026, FR-027, FR-028)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import (
    Conversation,
    Feedback,
    FeedbackRating,
    Turn,
    TurnKind,
    TurnTrace,
)
from app.ops.observability import AppError
from app.privacy.masker import mask_pii


async def upsert_turn_feedback(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    turn_id: uuid.UUID,
    rating: str,
    comment: str | None = None,
) -> dict[str, Any]:
    if comment is not None and len(comment) > 2000:
        raise AppError(400, "comment_too_long", "Ghi chú phản hồi không được vượt quá 2.000 ký tự.")

    row = (
        await session.execute(
            select(Turn, Conversation)
            .join(Conversation, Conversation.id == Turn.conversation_id)
            .where(Turn.id == turn_id)
        )
    ).first()
    if row is None:
        raise AppError(404, "turn_not_found", "Không tìm thấy lượt hỏi đáp.")
    turn, conv = row
    if conv.user_id != user_id:
        raise AppError(404, "turn_not_found", "Không tìm thấy lượt hỏi đáp.")

    masked_comment: str | None = None
    if comment and comment.strip():
        masked_comment, _ = mask_pii(comment.strip())

    fb_rating = FeedbackRating(rating)
    existing = (
        await session.execute(select(Feedback).where(Feedback.turn_id == turn.id))
    ).scalar_one_or_none()

    if existing is None:
        existing = Feedback(
            turn_id=turn.id,
            user_id=user_id,
            rating=fb_rating,
            comment=masked_comment,
        )
        session.add(existing)
    else:
        existing.rating = fb_rating
        existing.comment = masked_comment

    await session.commit()
    return {
        "id": str(existing.id),
        "turn_id": str(existing.turn_id),
        "rating": existing.rating.value,
        "comment": existing.comment,
    }


def _percentile(sorted_vals: list[int], pct: float) -> int:
    if not sorted_vals:
        return 0
    idx = min(len(sorted_vals) - 1, max(0, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return int(sorted_vals[idx])


async def get_ops_metrics_summary(
    session: AsyncSession,
    *,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> dict[str, Any]:
    stmt = select(Turn)
    if from_dt is not None:
        stmt = stmt.where(Turn.created_at >= from_dt)
    if to_dt is not None:
        stmt = stmt.where(Turn.created_at <= to_dt)
    turns = list((await session.execute(stmt)).scalars().all())

    traces = list((await session.execute(select(TurnTrace))).scalars().all())
    feedbacks = list((await session.execute(select(Feedback))).scalars().all())

    total = len(turns)
    latencies = sorted(t.latency_ms for t in turns if t.latency_ms >= 0)
    ttfts = sorted(t.ttft_ms for t in turns if t.ttft_ms >= 0)

    error_count = sum(1 for t in turns if t.kind == TurnKind.error)
    not_found_count = sum(1 for t in turns if t.kind == TurnKind.refusal_not_found)
    clarify_count = sum(1 for t in turns if t.kind == TurnKind.clarification)
    limit_count = sum(1 for t in turns if t.limit_reached)

    helpful_count = sum(1 for f in feedbacks if f.rating == FeedbackRating.helpful)
    fb_total = len(feedbacks)

    daily_cost: dict[str, float] = {}
    total_cost = 0.0
    for tr in traces:
        day_key = tr.created_at.date().isoformat()
        c_val = float(tr.cost_usd)
        daily_cost[day_key] = round(daily_cost.get(day_key, 0.0) + c_val, 5)
        total_cost += c_val

    return {
        "total_turns": total,
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "ttft_p50_ms": _percentile(ttfts, 50),
        "ttft_p95_ms": _percentile(ttfts, 95),
        "error_rate": round(error_count / total, 4) if total else 0.0,
        "not_found_rate": round(not_found_count / total, 4) if total else 0.0,
        "clarification_rate": round(clarify_count / total, 4) if total else 0.0,
        "limit_reached_rate": round(limit_count / total, 4) if total else 0.0,
        "helpful_feedback_rate": round(helpful_count / fb_total, 4) if fb_total else 0.0,
        "total_feedback_count": fb_total,
        "total_cost_usd": round(total_cost, 5),
        "daily_cost_usd": daily_cost,
    }


async def list_ops_feedback(
    session: AsyncSession, *, rating: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Feedback, Turn).join(Turn, Turn.id == Feedback.turn_id).order_by(Feedback.created_at.desc())
    if rating:
        stmt = stmt.where(Feedback.rating == FeedbackRating(rating))
    rows = (await session.execute(stmt)).all()
    items: list[dict[str, Any]] = []
    for fb, turn in rows:
        masked_q, _ = mask_pii(turn.question)
        masked_a, _ = mask_pii(turn.answer)
        items.append(
            {
                "id": str(fb.id),
                "turn_id": str(fb.turn_id),
                "rating": fb.rating.value,
                "comment": fb.comment,
                "masked_question": masked_q,
                "masked_answer": masked_a,
                "kind": turn.kind.value,
                "created_at": fb.created_at.isoformat(),
            }
        )
    return items


async def get_ops_turn_trace(
    session: AsyncSession, *, turn_id: uuid.UUID
) -> dict[str, Any]:
    tr = (
        await session.execute(select(TurnTrace).where(TurnTrace.turn_id == turn_id))
    ).scalar_one_or_none()
    if tr is None:
        raise AppError(404, "trace_not_found", "Không tìm thấy bản ghi trace cho lượt hỏi này.")

    fb = (
        await session.execute(select(Feedback).where(Feedback.turn_id == turn_id))
    ).scalar_one_or_none()

    return {
        "turn_id": str(tr.turn_id),
        "trace_id": tr.trace_id,
        "total_tokens": tr.total_tokens,
        "cost_usd": float(tr.cost_usd),
        "data": tr.data,
        "feedback": (
            {
                "rating": fb.rating.value,
                "comment": fb.comment,
            }
            if fb
            else None
        ),
        "created_at": tr.created_at.isoformat(),
    }
