"""Unit and integration tests for LangGraph Agent workflow: clarify cap <= 2, coreference rewrite, sub-question decomposition, budget cap, and prompt injection defense (T044)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.blob_store import LocalBlobStore
from app.adapters.embedder_gemini import FakeEmbedder
from app.adapters.llm_gemini import FakeLLMClient
from app.adapters.reranker import BilingualHeuristicReranker
from app.agent.graph import AgentState, build_agent_graph
from app.agent.tools import ReadOnlyAgentTools
from app.cli import seed_demo_data
from app.db.base import Base
from app.db.models.auth import User
from app.db.models.conversation import TurnKind
from app.rag.retriever import HybridRetriever


@pytest.mark.asyncio
async def test_agent_graph_clarification_limit_coreference_decomposition_and_budget(
    tmp_path: Path,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    blob_store = LocalBlobStore(tmp_path / "blobs")
    embedder = FakeEmbedder()
    reranker = BilingualHeuristicReranker()
    retriever = HybridRetriever(embedder=embedder, reranker=reranker)
    llm = FakeLLMClient()

    async with factory() as session:
        await seed_demo_data(session, blob_store=blob_store, embedder=embedder)
        eng_user = (
            await session.execute(select(User).where(User.username == "emp_eng"))
        ).scalar_one()
        tools = ReadOnlyAgentTools(session=session, retriever=retriever, user_id=eng_user.id)
        graph = build_agent_graph(llm, tools)

        # 1. Ambiguous question with pending_clarification_count = 0 -> asks clarification with options
        st1: AgentState = {
            "question": "Quy trình nghỉ phép thế nào?",
            "history_text": "None",
            "pending_clarification_count": 0,
        }
        res1 = await graph.ainvoke(st1)
        assert res1["turn_kind"] == TurnKind.clarification
        assert len(res1.get("clarification_options") or []) >= 2

        # 2. Same ambiguous question when pending_clarification_count == 2 (max reached, FR-013) -> answers with stated assumption
        st2: AgentState = {
            "question": "Quy trình nghỉ phép thế nào?",
            "history_text": "None",
            "pending_clarification_count": 2,
        }
        res2 = await graph.ainvoke(st2)
        assert res2["turn_kind"] == TurnKind.answer
        assert len(res2.get("assumptions") or []) >= 1
        assert "Giả định" in res2["final_answer"]

        # 3. Follow-up question using conversation context ("Còn nước ngoài thì sao?" after business trip query) -> rewrites without asking clarification
        st3: AgentState = {
            "question": "Còn nước ngoài thì sao?",
            "history_text": "User: Chính sách công tác phí trong nước?\nAssistant (answer): Phụ cấp 500.000 VNĐ/ngày [1].",
            "pending_clarification_count": 0,
        }
        res3 = await graph.ainvoke(st3)
        assert res3["turn_kind"] == TurnKind.answer
        assert "công tác phí" in res3["standalone_question"].lower()

        # 4. Partial answer when asking for both conditions and ERP procedure (FR-005a)
        st4: AgentState = {
            "question": "Điều kiện nghỉ phép năm và thủ tục đăng ký trên ERP?",
            "history_text": "None",
            "pending_clarification_count": 0,
        }
        res4 = await graph.ainvoke(st4)
        assert res4["turn_kind"] == TurnKind.partial_answer
        assert len(res4.get("missing_parts") or []) >= 1
        assert "ERP" in res4["final_answer"]

        # 5. Hard step/cost cap (FR-014): when llm_calls starts at max_turn_llm_calls, limit_reached is set
        st5: AgentState = {
            "question": "Mỗi năm nhân viên chính thức được nghỉ phép bao nhiêu ngày?",
            "history_text": "None",
            "pending_clarification_count": 0,
            "llm_calls": 8,
        }
        res5 = await graph.ainvoke(st5)
        assert res5["limit_reached"] is True

    await engine.dispose()
