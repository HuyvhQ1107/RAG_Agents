"""LangGraph Query-Understanding & Grounded RAG Agent (T047, FR-010..FR-015, R9)."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agent.tools import (
    FindDocumentsByTitleInput,
    ReadOnlyAgentTools,
    SearchDocumentsInput,
)
from app.config import get_settings
from app.db.models.conversation import TurnKind
from app.ports.providers import LLMClient, LLMUsage
from app.rag.citation_verifier import VerifiedCitation, verify_citations
from app.rag.prompt_loader import load_prompt
from app.rag.retriever import RetrievedPassage
from app.rag.summarizer import (
    format_sources_xml,
    load_document_passages_for_summary,
    summarize_single_document,
)


class ClarificationOptionSchema(BaseModel):
    id: str
    label: str


class QueryAnalysisResult(BaseModel):
    intent: Literal[
        "lookup",
        "summarize_document",
        "aggregate_unsupported",
        "out_of_scope",
        "clarification_reply",
    ] = "lookup"
    answer_language: Literal["vi", "en"] = "vi"
    clarity: Literal["clear", "ambiguous"] = "clear"
    standalone_question: str = ""
    search_queries: list[str] = Field(default_factory=list)
    sub_questions: list[str] = Field(default_factory=list)
    clarifying_question: str | None = None
    options: list[ClarificationOptionSchema] = Field(default_factory=list)
    target_document_hint: str | None = None


class EvidenceGradeResult(BaseModel):
    status: Literal["sufficient", "partial", "insufficient"] = "sufficient"
    missing_parts: list[str] = Field(default_factory=list)
    rewritten_query: str | None = None


class AgentState(TypedDict, total=False):
    question: str
    history_text: str
    scope_document_id: str | None
    scope_document_title: str | None
    pending_clarification_count: int
    clarification_choice_label: str | None
    as_of_date: str | None

    # Outputs of analyze
    intent: str
    answer_language: Literal["vi", "en"]
    clarity: Literal["clear", "ambiguous"]
    standalone_question: str
    search_queries: list[str]
    sub_questions: list[str]
    clarifying_question: str | None
    clarification_options: list[dict[str, str]]
    target_document_hint: str | None
    assumptions: list[str]

    # Retrieval & grading
    retrieval_rounds: int
    passages: list[RetrievedPassage]
    evidence_status: str
    missing_parts: list[str]

    # Budget & Trace
    llm_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float
    limit_reached: bool
    trace_steps: list[dict[str, Any]]

    # Final output
    turn_kind: TurnKind
    raw_answer: str
    final_answer: str
    verified_citations: list[VerifiedCitation]
    removed_markers: list[int]


def _can_call_llm(state: AgentState) -> bool:
    settings = get_settings()
    if state.get("llm_calls", 0) >= settings.max_turn_llm_calls:
        return False
    if state.get("total_prompt_tokens", 0) >= settings.max_turn_input_tokens:
        return False
    if state.get("total_cost_usd", 0.0) >= settings.max_turn_cost_usd:
        return False
    return True


def _record_usage(state: AgentState, step: str, usage: LLMUsage, extra: dict[str, Any] | None = None) -> None:
    state["llm_calls"] = state.get("llm_calls", 0) + 1
    state["total_prompt_tokens"] = state.get("total_prompt_tokens", 0) + usage.prompt_tokens
    state["total_completion_tokens"] = (
        state.get("total_completion_tokens", 0) + usage.completion_tokens
    )
    state["total_cost_usd"] = round(state.get("total_cost_usd", 0.0) + usage.cost_usd, 6)
    entry: dict[str, Any] = {
        "step": step,
        "model": usage.model,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cost_usd": usage.cost_usd,
        "latency_ms": usage.latency_ms,
    }
    if extra:
        entry.update(extra)
    state.setdefault("trace_steps", []).append(entry)


def build_agent_graph(llm: LLMClient, tools: ReadOnlyAgentTools) -> Any:
    settings = get_settings()

    async def analyze_node(state: AgentState) -> AgentState:
        question = state["question"]
        if state.get("clarification_choice_label"):
            question = f"{state.get('history_text', '')}\nLựa chọn làm rõ: {state['clarification_choice_label']}"

        if not _can_call_llm(state):
            state["limit_reached"] = True
            state["intent"] = "lookup"
            state["answer_language"] = "vi"
            state["clarity"] = "clear"
            state["standalone_question"] = question
            state["search_queries"] = [question]
            return state

        tmpl = load_prompt("analyze_query", "v1")
        sys_p, user_p = tmpl.render(
            scope_document=state.get("scope_document_title") or "None",
            history=state.get("history_text") or "None",
            question=question,
        )
        analysis, usage = await llm.generate_structured(
            role="fast",
            system_prompt=sys_p,
            user_prompt=user_p,
            response_model=QueryAnalysisResult,
        )
        _record_usage(
            state,
            "analyze",
            usage,
            {
                "intent": analysis.intent,
                "clarity": analysis.clarity,
                "standalone_question": analysis.standalone_question,
                "search_queries": analysis.search_queries,
                "sub_questions": analysis.sub_questions,
            },
        )

        state["intent"] = analysis.intent
        state["answer_language"] = analysis.answer_language
        state["standalone_question"] = analysis.standalone_question or question
        state["search_queries"] = (analysis.search_queries or [question])[:4]
        state["sub_questions"] = analysis.sub_questions[:3]
        state["target_document_hint"] = analysis.target_document_hint
        state["clarity"] = analysis.clarity

        # Enforce max 2 clarifications rule (FR-012, FR-013)
        clar_count = state.get("pending_clarification_count", 0)
        if analysis.clarity == "ambiguous":
            if clar_count >= settings.max_clarifications_per_question:
                state["clarity"] = "clear"
                default_opt = (
                    analysis.options[0].label
                    if analysis.options
                    else ("Nhân viên chính thức" if analysis.answer_language == "vi" else "Full-time employee")
                )
                assumption_msg = (
                    f"Giả định áp dụng: {default_opt}"
                    if analysis.answer_language == "vi"
                    else f"Applied assumption: {default_opt}"
                )
                state["assumptions"] = [assumption_msg]
                state["standalone_question"] = f"{state['standalone_question']} ({default_opt})"
                state["search_queries"] = [state["standalone_question"], *state["search_queries"]][:4]
            else:
                state["clarifying_question"] = analysis.clarifying_question or (
                    "Bạn có thể làm rõ hơn yêu cầu của mình không?"
                    if analysis.answer_language == "vi"
                    else "Could you clarify your question?"
                )
                state["clarification_options"] = [
                    {"id": o.id, "label": o.label} for o in analysis.options
                ] or [
                    {"id": "official", "label": "Nhân viên chính thức"},
                    {"id": "probation", "label": "Nhân viên thử việc"},
                ]

        return state

    async def ask_clarification_node(state: AgentState) -> AgentState:
        state["turn_kind"] = TurnKind.clarification
        state["final_answer"] = state.get("clarifying_question") or ""
        state["verified_citations"] = []
        return state

    async def refuse_unsupported_node(state: AgentState) -> AgentState:
        lang = state.get("answer_language", "vi")
        if state.get("intent") == "out_of_scope":
            state["turn_kind"] = TurnKind.refusal_out_of_scope
            state["final_answer"] = (
                "I can only answer questions based on internal company documents and policies. "
                "Please ask a question related to internal procedures or guidelines."
                if lang == "en"
                else "Xin lỗi, tôi chỉ hỗ trợ trả lời các câu hỏi dựa trên tài liệu và quy định nội bộ của công ty. "
                "Bạn vui lòng đặt câu hỏi về quy trình, chính sách hoặc tài liệu nội bộ nhé."
            )
        else:
            state["turn_kind"] = TurnKind.refusal_unsupported
            state["final_answer"] = (
                "Corpus-wide aggregation or comparison across all documents is not supported in this version. "
                "Please narrow your request to a specific policy topic or select a single document to summarize."
                if lang == "en"
                else "Hệ thống hiện chưa hỗ trợ tổng hợp hoặc liệt kê trên toàn bộ kho tài liệu. "
                "Bạn vui lòng hỏi về một chủ đề cụ thể hoặc chọn một tài liệu cụ thể để tóm tắt."
            )
        state["verified_citations"] = []
        return state

    async def summarize_node(state: AgentState) -> AgentState:
        lang = state.get("answer_language", "vi")
        as_of = (
            date.fromisoformat(state["as_of_date"])
            if state.get("as_of_date")
            else None
        )
        target_doc_id: uuid.UUID | None = (
            uuid.UUID(state["scope_document_id"])
            if state.get("scope_document_id")
            else None
        )

        if target_doc_id is None:
            hint = state.get("target_document_hint") or state.get("standalone_question") or ""
            candidates = await tools.find_documents_by_title(
                FindDocumentsByTitleInput(title_query=hint)
            )
            if not candidates:
                state["turn_kind"] = TurnKind.refusal_not_found
                state["final_answer"] = (
                    "Could not find the requested document in your accessible library."
                    if lang == "en"
                    else "Không tìm thấy tài liệu bạn yêu cầu trong phạm vi tài liệu bạn có quyền xem."
                )
                state["verified_citations"] = []
                return state
            if len(candidates) > 1 and state.get("pending_clarification_count", 0) < settings.max_clarifications_per_question:
                state["turn_kind"] = TurnKind.clarification
                state["clarifying_question"] = (
                    "Which document would you like to summarize?"
                    if lang == "en"
                    else "Bạn muốn tóm tắt tài liệu nào dưới đây?"
                )
                state["final_answer"] = state["clarifying_question"]
                state["clarification_options"] = [
                    {"id": c.id, "label": c.title} for c in candidates[:4]
                ]
                state["verified_citations"] = []
                return state
            target_doc_id = uuid.UUID(candidates[0].id)

        loaded = await load_document_passages_for_summary(
            tools.session,
            user_id=tools.user_id,
            document_id=target_doc_id,
            as_of_date=as_of,
        )
        if loaded is None or not loaded[2]:
            state["turn_kind"] = TurnKind.refusal_not_found
            state["final_answer"] = (
                "Could not find content to summarize in the selected document."
                if lang == "en"
                else "Không tìm thấy nội dung tài liệu để tóm tắt."
            )
            state["verified_citations"] = []
            return state

        doc, _ver, passages = loaded
        state["passages"] = passages
        raw_summary, usages = await summarize_single_document(
            llm,
            document_title=doc.title,
            question=state.get("standalone_question") or state["question"],
            language=lang,
            passages=passages,
            as_of_date=as_of,
        )
        for u in usages:
            _record_usage(state, "summarize", u, {"document_id": str(doc.id)})

        ver_res = verify_citations(raw_summary, passages)
        state["turn_kind"] = TurnKind.answer
        state["raw_answer"] = raw_summary
        state["final_answer"] = ver_res.cleaned_answer
        state["verified_citations"] = ver_res.citations
        state["removed_markers"] = ver_res.removed_markers
        return state

    async def retrieve_node(state: AgentState) -> AgentState:
        rounds = state.get("retrieval_rounds", 0) + 1
        state["retrieval_rounds"] = rounds
        scope_id = (
            uuid.UUID(state["scope_document_id"])
            if state.get("scope_document_id")
            else None
        )
        queries = list(state.get("search_queries") or [state["standalone_question"]])
        for sq in state.get("sub_questions") or []:
            if sq not in queries:
                queries.append(sq)

        passages = await tools.search_documents(
            SearchDocumentsInput(
                queries=queries[:4],
                scope_document_id=scope_id,
                top_k=8,
            )
        )
        # Merge unique passages preserving order
        existing = {p.chunk_id: p for p in state.get("passages") or []}
        for p in passages:
            if p.chunk_id not in existing:
                existing[p.chunk_id] = p
        merged = list(existing.values())[:8]
        state["passages"] = merged
        state.setdefault("trace_steps", []).append(
            {
                "step": f"retrieve_round_{rounds}",
                "queries": queries[:4],
                "retrieved_chunks": [
                    {
                        "chunk_id": str(p.chunk_id),
                        "document_title": p.document_title,
                        "section_path": p.section_path,
                        "dense_score": p.dense_score,
                        "lexical_score": p.lexical_score,
                        "rerank_score": p.rerank_score,
                    }
                    for p in merged
                ],
            }
        )
        return state

    async def grade_node(state: AgentState) -> AgentState:
        passages = state.get("passages") or []
        if not passages:
            state["evidence_status"] = "insufficient"
            return state

        if not _can_call_llm(state):
            state["limit_reached"] = True
            state["evidence_status"] = "sufficient"
            return state

        as_of = (
            date.fromisoformat(state["as_of_date"])
            if state.get("as_of_date")
            else None
        )
        tmpl = load_prompt("grade_evidence", "v1")
        sys_p, user_p = tmpl.render(
            question=state.get("standalone_question") or state["question"],
            sub_questions=json.dumps(state.get("sub_questions") or [], ensure_ascii=False),
            sources=format_sources_xml(passages, as_of_date=as_of),
        )
        grade_res, usage = await llm.generate_structured(
            role="fast",
            system_prompt=sys_p,
            user_prompt=user_p,
            response_model=EvidenceGradeResult,
        )
        _record_usage(
            state,
            "grade",
            usage,
            {
                "status": grade_res.status,
                "missing_parts": grade_res.missing_parts,
                "rewritten_query": grade_res.rewritten_query,
            },
        )
        state["evidence_status"] = grade_res.status
        state["missing_parts"] = grade_res.missing_parts
        if (
            grade_res.status == "insufficient"
            and grade_res.rewritten_query
            and state.get("retrieval_rounds", 1) < settings.max_retrieval_rounds
        ):
            state["search_queries"] = [grade_res.rewritten_query]
        return state

    async def generate_node(state: AgentState) -> AgentState:
        lang = state.get("answer_language", "vi")
        passages = state.get("passages") or []
        if not passages or state.get("evidence_status") == "insufficient":
            state["turn_kind"] = TurnKind.refusal_not_found
            scope_note = ""
            if state.get("scope_document_id"):
                scope_note = (
                    " in the currently selected document (you may clear the document scope to search all permitted documents)"
                    if lang == "en"
                    else " trong tài liệu đang chọn (bạn có thể gỡ giới hạn phạm vi tài liệu để tìm trên toàn bộ tài liệu được phép)"
                )
            state["final_answer"] = (
                f"Could not find relevant information{scope_note} in the internal documents."
                if lang == "en"
                else f"Không tìm thấy thông tin liên quan{scope_note} trong tài liệu nội bộ."
            )
            state["verified_citations"] = []
            return state

        if not _can_call_llm(state):
            state["limit_reached"] = True

        as_of = (
            date.fromisoformat(state["as_of_date"])
            if state.get("as_of_date")
            else None
        )
        tmpl = load_prompt("generate_answer", "v1")
        sys_p, user_p = tmpl.render(
            language=lang,
            assumptions=json.dumps(state.get("assumptions") or [], ensure_ascii=False),
            missing_parts=json.dumps(state.get("missing_parts") or [], ensure_ascii=False),
            question=state.get("standalone_question") or state["question"],
            sources=format_sources_xml(passages, as_of_date=as_of),
        )
        raw_text, usage = await llm.generate_text(
            role="answer",
            system_prompt=sys_p,
            user_prompt=user_p,
        )
        _record_usage(state, "generate", usage)

        # Prepend explicit assumption notice if FR-013 triggered
        assumptions = state.get("assumptions") or []
        if assumptions:
            prefix = " ".join(assumptions) + ". "
            if prefix.lower() not in raw_text.lower():
                raw_text = prefix + raw_text

        ver_res = verify_citations(raw_text, passages)
        state["raw_answer"] = raw_text
        state["final_answer"] = ver_res.cleaned_answer
        state["verified_citations"] = ver_res.citations
        state["removed_markers"] = ver_res.removed_markers
        state["turn_kind"] = (
            TurnKind.partial_answer
            if state.get("missing_parts")
            else TurnKind.answer
        )
        return state

    def route_after_analyze(state: AgentState) -> str:
        intent = state.get("intent", "lookup")
        if intent in ("out_of_scope", "aggregate_unsupported"):
            return "refuse_unsupported"
        if state.get("clarity") == "ambiguous":
            return "ask_clarification"
        if intent == "summarize_document":
            return "summarize"
        return "retrieve"

    def route_after_grade(state: AgentState) -> str:
        if (
            state.get("evidence_status") == "insufficient"
            and state.get("retrieval_rounds", 1) < settings.max_retrieval_rounds
            and _can_call_llm(state)
        ):
            return "retrieve"
        return "generate"

    builder = StateGraph(AgentState)
    builder.add_node("analyze", analyze_node)
    builder.add_node("ask_clarification", ask_clarification_node)
    builder.add_node("refuse_unsupported", refuse_unsupported_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("grade", grade_node)
    builder.add_node("generate", generate_node)

    builder.add_edge(START, "analyze")
    builder.add_conditional_edges(
        "analyze",
        route_after_analyze,
        {
            "ask_clarification": "ask_clarification",
            "refuse_unsupported": "refuse_unsupported",
            "summarize": "summarize",
            "retrieve": "retrieve",
        },
    )
    builder.add_edge("ask_clarification", END)
    builder.add_edge("refuse_unsupported", END)
    builder.add_edge("summarize", END)
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges(
        "grade",
        route_after_grade,
        {
            "retrieve": "retrieve",
            "generate": "generate",
        },
    )
    builder.add_edge("generate", END)

    return builder.compile()
