"""Conversation & Turn Service with SSE streaming, rate limiting, PII restoration, and trace recording (T033, T040, T048)."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import AgentState, build_agent_graph
from app.agent.tools import ReadOnlyAgentTools
from app.config import get_settings
from app.db.base import utcnow
from app.db.models.auth import PreferredLanguage
from app.db.models.conversation import Citation, Conversation, Turn, TurnKind, TurnTrace
from app.db.models.document import Document
from app.ops.observability import (
    TURN_COUNTER,
    TURN_LATENCY_HISTOGRAM,
    TURN_TTFT_HISTOGRAM,
    AppError,
    get_current_trace_id,
)
from app.ports.providers import LLMClient
from app.privacy.masker import PIIMaskingSession
from app.rag.access_filter import verify_user_can_access_document
from app.rag.retriever import HybridRetriever

# In-memory concurrency lock & rate limiter per conversation / user
_active_conversation_turns: set[uuid.UUID] = set()
_cancelled_turns: set[uuid.UUID] = set()
_user_request_timestamps: dict[uuid.UUID, list[float]] = defaultdict(list)


def reset_rate_limits() -> None:
    _active_conversation_turns.clear()
    _cancelled_turns.clear()
    _user_request_timestamps.clear()


def cancel_active_turn(turn_id: uuid.UUID) -> None:
    _cancelled_turns.add(turn_id)


def _check_rate_limit(user_id: uuid.UUID) -> None:
    settings = get_settings()
    now = time.monotonic()
    window = [t for t in _user_request_timestamps[user_id] if now - t < 60.0]
    if len(window) >= settings.rate_limit_questions_per_minute:
        raise AppError(
            429,
            "rate_limited",
            "Bạn đã gửi quá số lượng câu hỏi cho phép trong một phút. Vui lòng thử lại sau.",
        )
    window.append(now)
    _user_request_timestamps[user_id] = window


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ConversationService:
    def __init__(self, llm: LLMClient, retriever: HybridRetriever) -> None:
        self.llm = llm
        self.retriever = retriever
        self.settings = get_settings()

    async def create_conversation(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        scope_document_id: uuid.UUID | None = None,
        title: str | None = None,
    ) -> Conversation:
        if scope_document_id is not None:
            doc = await verify_user_can_access_document(session, user_id, scope_document_id)
            if doc is None:
                raise AppError(404, "document_not_found", "Không tìm thấy tài liệu.")
        conv = Conversation(
            user_id=user_id,
            title=title or "Hội thoại mới",
            scope_document_id=scope_document_id,
            pending_clarification_count=0,
            last_activity_at=utcnow(),
        )
        session.add(conv)
        await session.commit()
        return conv

    async def list_conversations(
        self, session: AsyncSession, *, user_id: uuid.UUID, limit: int = 20
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.last_activity_at.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_conversation_detail(
        self, session: AsyncSession, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> dict[str, Any]:
        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id, Conversation.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise AppError(404, "conversation_not_found", "Không tìm thấy cuộc hội thoại.")

        scope_title: str | None = None
        if conv.scope_document_id:
            sdoc = await verify_user_can_access_document(session, user_id, conv.scope_document_id)
            if sdoc:
                scope_title = sdoc.title
            else:
                conv.scope_document_id = None
                await session.commit()

        turns = list(
            (
                await session.execute(
                    select(Turn)
                    .where(Turn.conversation_id == conv.id)
                    .order_by(Turn.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )
        turn_items: list[dict[str, Any]] = []
        for t in turns:
            cits = list(
                (
                    await session.execute(
                        select(Citation)
                        .where(Citation.turn_id == t.id)
                        .order_by(Citation.marker.asc())
                    )
                )
                .scalars()
                .all()
            )
            turn_items.append(
                {
                    "id": str(t.id),
                    "ordinal": t.ordinal,
                    "question": t.question,
                    "kind": t.kind.value,
                    "answer_language": t.answer_language.value,
                    "answer": t.answer,
                    "clarification_options": t.clarification_options,
                    "assumptions": t.assumptions,
                    "missing_parts": t.missing_parts,
                    "limit_reached": t.limit_reached,
                    "latency_ms": t.latency_ms,
                    "citations": [
                        {
                            "marker": c.marker,
                            "citation_id": str(c.id),
                            "document_id": str(c.document_id),
                            "document_title": c.document_title,
                            "version_number": c.version_number,
                            "section_path": c.section_path,
                            "page_start": c.page_start,
                            "page_end": c.page_end,
                            "effective_from": (
                                c.effective_from.isoformat() if c.effective_from else None
                            ),
                            "snippet": c.snippet,
                        }
                        for c in cits
                    ],
                }
            )

        return {
            "id": str(conv.id),
            "title": conv.title,
            "scope_document_id": str(conv.scope_document_id) if conv.scope_document_id else None,
            "scope_document_title": scope_title,
            "pending_clarification_count": conv.pending_clarification_count,
            "turns": turn_items,
        }

    async def update_conversation(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        title: str | None = None,
        scope_document_id: uuid.UUID | None = None,
        update_scope: bool = False,
    ) -> Conversation:
        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id, Conversation.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise AppError(404, "conversation_not_found", "Không tìm thấy cuộc hội thoại.")

        if title is not None:
            masked_title = PIIMaskingSession().mask(title.strip())[:120]
            conv.title = masked_title or conv.title

        if update_scope:
            if scope_document_id is not None:
                doc = await verify_user_can_access_document(session, user_id, scope_document_id)
                if doc is None:
                    raise AppError(404, "document_not_found", "Không tìm thấy tài liệu.")
            conv.scope_document_id = scope_document_id

        await session.commit()
        return conv

    async def delete_conversation(
        self, session: AsyncSession, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> None:
        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id, Conversation.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise AppError(404, "conversation_not_found", "Không tìm thấy cuộc hội thoại.")
        await session.execute(delete(Conversation).where(Conversation.id == conv.id))
        await session.commit()

    async def stream_message(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        clarification_choice: dict[str, Any] | None = None,
        as_of_date: date | None = None,
    ) -> AsyncIterator[str]:
        if not content or not content.strip() or len(content) > 4000:
            raise AppError(400, "invalid_question", "Câu hỏi phải có độ dài từ 1 đến 4.000 ký tự.")

        _check_rate_limit(user_id)

        conv = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id, Conversation.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if conv is None:
            raise AppError(404, "conversation_not_found", "Không tìm thấy cuộc hội thoại.")

        if conv.id in _active_conversation_turns:
            raise AppError(
                409,
                "turn_in_progress",
                "Đang có một câu hỏi được xử lý trong hội thoại này.",
            )

        _active_conversation_turns.add(conv.id)
        trace_id = get_current_trace_id()
        start_perf = time.perf_counter()

        # Re-verify scope document permission on every turn (FR-019)
        scope_doc: Document | None = None
        if conv.scope_document_id is not None:
            scope_doc = await verify_user_can_access_document(
                session, user_id, conv.scope_document_id, as_of_date=as_of_date
            )
            if scope_doc is None:
                conv.scope_document_id = None

        # Determine next ordinal and recent 6 turns history
        recent_turns = list(
            (
                await session.execute(
                    select(Turn)
                    .where(Turn.conversation_id == conv.id)
                    .order_by(Turn.ordinal.desc())
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )
        recent_turns.reverse()
        next_ordinal = (recent_turns[-1].ordinal + 1) if recent_turns else 1

        # Reversible PII session for this request
        pii_session = PIIMaskingSession()
        masked_question = pii_session.mask(content.strip())

        if next_ordinal == 1 and conv.title == "Hội thoại mới":
            conv.title = masked_question[:80]

        # Handle clarification reply vs new standalone question (Edge Case: user ignores clarification and asks new question)
        choice_label: str | None = None
        if clarification_choice and isinstance(clarification_choice, dict):
            choice_label = pii_session.mask(str(clarification_choice.get("label") or content.strip()))
        elif recent_turns and recent_turns[-1].kind == TurnKind.clarification:
            # Check if user's message matches one of the previous options or is a direct short answer
            prev_opts = recent_turns[-1].clarification_options or []
            matched_opt = next(
                (
                    o["label"]
                    for o in prev_opts
                    if o.get("id", "").lower() == content.strip().lower()
                    or o.get("label", "").lower() in content.strip().lower()
                ),
                None,
            )
            if matched_opt:
                choice_label = pii_session.mask(matched_opt)
            elif "?" in content and len(content.split()) >= 5:
                # User ignored clarification and asked a brand new question! Reset counter.
                conv.pending_clarification_count = 0
            else:
                choice_label = masked_question
        else:
            conv.pending_clarification_count = 0

        # Pre-create Turn row
        turn = Turn(
            conversation_id=conv.id,
            ordinal=next_ordinal,
            question=content.strip(),
            kind=TurnKind.answer,
            answer_language=PreferredLanguage.vi,
            answer="",
            scope_document_id=scope_doc.id if scope_doc else None,
            trace_id=trace_id,
        )
        session.add(turn)
        await session.flush()

        async def _generator() -> AsyncIterator[str]:
            try:
                yield _sse_event(
                    "turn.started",
                    {
                        "turn_id": str(turn.id),
                        "trace_id": trace_id,
                        "scope_document": (
                            {"id": str(scope_doc.id), "title": scope_doc.title}
                            if scope_doc
                            else None
                        ),
                    },
                )
                yield _sse_event("status", {"stage": "analyzing"})

                history_lines: list[str] = []
                for rt in recent_turns:
                    q_m = pii_session.mask(rt.question)
                    a_m = pii_session.mask(rt.answer)
                    history_lines.append(f"User: {q_m}\nAssistant ({rt.kind.value}): {a_m}")

                tools = ReadOnlyAgentTools(
                    session=session,
                    retriever=self.retriever,
                    user_id=user_id,
                    as_of_date=as_of_date,
                )
                graph = build_agent_graph(self.llm, tools)

                init_state: AgentState = {
                    "question": masked_question,
                    "history_text": "\n".join(history_lines) if history_lines else "None",
                    "scope_document_id": str(scope_doc.id) if scope_doc else None,
                    "scope_document_title": scope_doc.title if scope_doc else None,
                    "pending_clarification_count": conv.pending_clarification_count,
                    "clarification_choice_label": choice_label,
                    "as_of_date": as_of_date.isoformat() if as_of_date else None,
                    "assumptions": [],
                    "missing_parts": [],
                    "retrieval_rounds": 0,
                    "llm_calls": 0,
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_cost_usd": 0.0,
                    "limit_reached": False,
                    "trace_steps": [],
                }

                result_state: AgentState = await graph.ainvoke(init_state)

                if turn.id in _cancelled_turns:
                    turn.kind = TurnKind.error
                    turn.answer = "Đã hủy theo yêu cầu người dùng."
                    await session.commit()
                    yield _sse_event(
                        "error",
                        {
                            "code": "cancelled",
                            "message": "Đã dừng sinh câu trả lời.",
                            "retryable": True,
                        },
                    )
                    return

                turn_kind: TurnKind = result_state.get("turn_kind", TurnKind.answer)
                ans_lang = result_state.get("answer_language", "vi")
                turn.kind = turn_kind
                turn.answer_language = (
                    PreferredLanguage.en if ans_lang == "en" else PreferredLanguage.vi
                )
                turn.assumptions = result_state.get("assumptions") or []
                turn.missing_parts = result_state.get("missing_parts") or []
                turn.limit_reached = bool(result_state.get("limit_reached", False))

                # Register all retrieved chunk raw PII in pii_session so placeholders in answer can be restored for authorized user
                for p in result_state.get("passages") or []:
                    pii_session.mask(p.content)

                masked_final_answer = result_state.get("final_answer") or ""
                display_answer = pii_session.unmask(masked_final_answer)
                turn.answer = display_answer

                ttft_ms = int((time.perf_counter() - start_perf) * 1000)

                if turn_kind == TurnKind.clarification:
                    conv.pending_clarification_count = min(
                        self.settings.max_clarifications_per_question,
                        conv.pending_clarification_count + 1,
                    )
                    opts = result_state.get("clarification_options") or []
                    turn.clarification_options = opts
                    remaining = max(
                        0,
                        self.settings.max_clarifications_per_question
                        - conv.pending_clarification_count,
                    )
                    yield _sse_event(
                        "clarification",
                        {
                            "question": display_answer,
                            "options": opts,
                            "allow_free_text": True,
                            "remaining_clarifications": remaining,
                        },
                    )
                else:
                    conv.pending_clarification_count = 0
                    stage = (
                        "reading_document"
                        if result_state.get("intent") == "summarize_document"
                        else "searching"
                    )
                    yield _sse_event("status", {"stage": stage})
                    yield _sse_event("status", {"stage": "writing"})

                    # Stream sentence-by-sentence deltas (already citation-verified)
                    sentences = [s for s in re.split(r"(?<=[.!?])\s+", display_answer) if s]
                    if not sentences and display_answer:
                        sentences = [display_answer]
                    for idx, sent in enumerate(sentences):
                        suffix = " " if idx < len(sentences) - 1 else ""
                        yield _sse_event("answer.delta", {"text": sent + suffix})

                    verified_cits = result_state.get("verified_citations") or []
                    citation_payload_items: list[dict[str, Any]] = []
                    for vc in verified_cits:
                        p = vc.passage
                        snippet = p.content[:300]
                        cit_row = Citation(
                            turn_id=turn.id,
                            marker=vc.marker,
                            chunk_id=p.chunk_id,
                            document_id=p.document_id,
                            document_version_id=p.document_version_id,
                            document_title=p.document_title,
                            version_number=p.version_number,
                            section_path=p.section_path,
                            page_start=p.page_start,
                            page_end=p.page_end,
                            effective_from=p.effective_from,
                            snippet=snippet,
                        )
                        session.add(cit_row)
                        await session.flush()
                        citation_payload_items.append(
                            {
                                "marker": vc.marker,
                                "citation_id": str(cit_row.id),
                                "document_id": str(p.document_id),
                                "document_title": p.document_title,
                                "version_number": p.version_number,
                                "section_path": p.section_path,
                                "page_start": p.page_start,
                                "page_end": p.page_end,
                                "effective_from": (
                                    p.effective_from.isoformat() if p.effective_from else None
                                ),
                                "snippet": snippet,
                            }
                        )

                    yield _sse_event("citations", {"items": citation_payload_items})

                latency_ms = int((time.perf_counter() - start_perf) * 1000)
                turn.ttft_ms = ttft_ms
                turn.latency_ms = latency_ms
                conv.last_activity_at = utcnow()

                # Persist PII-masked TurnTrace (FR-021, FR-027)
                total_tok = int(result_state.get("total_prompt_tokens", 0)) + int(
                    result_state.get("total_completion_tokens", 0)
                )
                cost_usd = float(result_state.get("total_cost_usd", 0.0))
                trace_data = {
                    "masked_question": masked_question,
                    "intent": result_state.get("intent"),
                    "clarity": result_state.get("clarity"),
                    "standalone_question": result_state.get("standalone_question"),
                    "search_queries": result_state.get("search_queries"),
                    "sub_questions": result_state.get("sub_questions"),
                    "assumptions": turn.assumptions,
                    "missing_parts": turn.missing_parts,
                    "masked_answer": masked_final_answer,
                    "removed_citation_markers": result_state.get("removed_markers") or [],
                    "steps": result_state.get("trace_steps") or [],
                    "latency_ms": latency_ms,
                    "ttft_ms": ttft_ms,
                }
                trace_row = TurnTrace(
                    turn_id=turn.id,
                    trace_id=trace_id,
                    data=trace_data,
                    total_tokens=total_tok,
                    cost_usd=Decimal(f"{cost_usd:.5f}"),
                )
                session.add(trace_row)
                await session.commit()

                TURN_COUNTER.labels(kind=turn.kind.value).inc()
                TURN_LATENCY_HISTOGRAM.labels(kind=turn.kind.value).observe(latency_ms / 1000.0)
                TURN_TTFT_HISTOGRAM.observe(ttft_ms / 1000.0)

                yield _sse_event(
                    "turn.completed",
                    {
                        "turn_id": str(turn.id),
                        "kind": turn.kind.value,
                        "answer_language": turn.answer_language.value,
                        "assumptions": turn.assumptions,
                        "missing_parts": turn.missing_parts,
                        "limit_reached": turn.limit_reached,
                        "latency_ms": latency_ms,
                    },
                )
            except Exception as exc:
                turn.kind = TurnKind.error
                turn.answer = "Dịch vụ tạm thời không phản hồi, vui lòng thử lại."
                await session.commit()
                yield _sse_event(
                    "error",
                    {
                        "code": "provider_unavailable",
                        "message": f"Dịch vụ tạm thời không phản hồi, vui lòng thử lại. ({exc})",
                        "retryable": True,
                    },
                )
            finally:
                _active_conversation_turns.discard(conv.id)
                _cancelled_turns.discard(turn.id)

        return _generator()
