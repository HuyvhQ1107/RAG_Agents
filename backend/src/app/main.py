"""FastAPI application factory wiring all routers, ports, and observability (T021, T064)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import func, select

from app.adapters.blob_store import LocalBlobStore
from app.adapters.embedder_gemini import FakeEmbedder, GeminiEmbedder
from app.adapters.llm_gemini import FakeLLMClient, GeminiLLMClient
from app.adapters.reranker import BilingualHeuristicReranker, GeminiFlashReranker
from app.api import (
    admin_documents,
    admin_users,
    auth,
    conversations,
    documents,
    feedback,
    health,
    ops,
)
from app.cli import seed_demo_data
from app.config import get_settings
from app.conversations.service import ConversationService
from app.db.base import Base, get_engine, get_session_factory
from app.db.models.auth import User
from app.ops.observability import install_observability
from app.ports.providers import BlobStore, Embedder, LLMClient, Reranker
from app.rag.retriever import HybridRetriever


def create_app(
    *,
    llm_client: LLMClient | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    blob_store: BlobStore | None = None,
) -> FastAPI:
    settings = get_settings()

    active_llm: LLMClient = llm_client or (
        GeminiLLMClient() if settings.gemini_api_key else FakeLLMClient()
    )
    active_embedder: Embedder = embedder or (
        GeminiEmbedder() if settings.gemini_api_key else FakeEmbedder()
    )
    active_reranker: Reranker = reranker or (
        GeminiFlashReranker(active_llm)
        if settings.reranker_provider == "gemini_flash"
        else BilingualHeuristicReranker()
    )
    active_blob_store: BlobStore = blob_store or LocalBlobStore()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings.database_url.startswith("sqlite"):
            from app.auth.service import hash_password
            from app.db.models.auth import PreferredLanguage, UserStatus

            Path(".data").mkdir(parents=True, exist_ok=True)
            engine = get_engine()
            async with engine.begin() as conn:
                await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                await conn.run_sync(Base.metadata.create_all)
            factory = get_session_factory()
            async with factory() as session:
                user_count = (
                    await session.execute(select(func.count()).select_from(User))
                ).scalar_one()
                if user_count == 0:
                    await seed_demo_data(
                        session,
                        blob_store=active_blob_store,
                        embedder=active_embedder,
                    )
                else:
                    adm = (
                        await session.execute(select(User).where(User.username == "admin"))
                    ).scalar_one_or_none()
                    if adm is not None:
                        adm.password_hash = hash_password("AdminPass123!")
                        adm.failed_login_count = 0
                        adm.locked_until = None
                        adm.status = UserStatus.active
                    op = (
                        await session.execute(select(User).where(User.username == "operator"))
                    ).scalar_one_or_none()
                    if op is None:
                        session.add(
                            User(
                                username="operator",
                                display_name="Chuyên viên Vận hành (Ops)",
                                email="ops@company.local",
                                password_hash=hash_password("OperatorPass123!"),
                                must_change_password=False,
                                roles=["employee", "operator"],
                                status=UserStatus.active,
                                preferred_language=PreferredLanguage.vi,
                            )
                        )
                    else:
                        op.password_hash = hash_password("OperatorPass123!")
                        op.failed_login_count = 0
                        op.locked_until = None
                        op.status = UserStatus.active
                    await session.commit()
        yield

    app = FastAPI(
        title="RAG_Agents — Hỏi đáp tài liệu nội bộ song ngữ",
        version="1.0.0",
        lifespan=lifespan,
    )

    install_observability(app)

    retriever = HybridRetriever(embedder=active_embedder, reranker=active_reranker)
    conv_service = ConversationService(llm=active_llm, retriever=retriever)

    app.state.llm_client = active_llm
    app.state.embedder = active_embedder
    app.state.reranker = active_reranker
    app.state.blob_store = active_blob_store
    app.state.retriever = retriever
    app.state.conversation_service = conv_service

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(documents.router)
    app.include_router(feedback.router)
    app.include_router(admin_users.router)
    app.include_router(admin_documents.router)
    app.include_router(ops.router)

    return app


app = create_app()
