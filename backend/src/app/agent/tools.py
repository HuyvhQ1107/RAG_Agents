"""Bounded Read-Only Agent Tools with strict Pydantic schemas and mandatory access control (T046, FR-015, Constitution V)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Chunk, Document
from app.rag.access_filter import (
    build_accessible_documents_predicate,
    verify_user_can_access_document,
)
from app.rag.retriever import HybridRetriever, RetrievedPassage


class SearchDocumentsInput(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=4)
    scope_document_id: uuid.UUID | None = None
    top_k: int = Field(default=8, ge=1, le=20)


class DocumentCandidateItem(BaseModel):
    id: str
    title: str
    effective_from: str | None = None
    expires_on: str | None = None
    language: str


class FindDocumentsByTitleInput(BaseModel):
    title_query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=25)


class DocumentOutlineSection(BaseModel):
    ordinal: int
    section_path: str
    page_start: int | None = None


class GetDocumentOutlineInput(BaseModel):
    document_id: uuid.UUID


class ReadOnlyAgentTools:
    """Strictly read-only tools exposed to the Agent (search_documents, get_document_outline, find_documents_by_title)."""

    def __init__(
        self,
        session: AsyncSession,
        retriever: HybridRetriever,
        user_id: uuid.UUID,
        as_of_date: date | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.session = session
        self.retriever = retriever
        self.user_id = user_id
        self.as_of_date = as_of_date
        self.timeout_seconds = timeout_seconds

    async def search_documents(self, params: SearchDocumentsInput) -> list[RetrievedPassage]:
        return await asyncio.wait_for(
            self.retriever.search(
                self.session,
                user_id=self.user_id,
                queries=params.queries,
                scope_document_id=params.scope_document_id,
                as_of_date=self.as_of_date,
                top_k=params.top_k,
            ),
            timeout=self.timeout_seconds,
        )

    async def find_documents_by_title(
        self, params: FindDocumentsByTitleInput
    ) -> list[DocumentCandidateItem]:
        q_norm = params.title_query.strip().lower()
        stmt = (
            select(Document)
            .where(
                build_accessible_documents_predicate(
                    user_id=self.user_id,
                    as_of_date=self.as_of_date,
                )
            )
            .order_by(Document.title.asc())
        )
        docs = list((await self.session.execute(stmt)).scalars().all())
        matched = [d for d in docs if q_norm in d.title.lower() or d.title.lower() in q_norm]
        return [
            DocumentCandidateItem(
                id=str(d.id),
                title=d.title,
                effective_from=d.effective_from.isoformat() if d.effective_from else None,
                expires_on=d.expires_on.isoformat() if d.expires_on else None,
                language="vi",
            )
            for d in matched[: params.limit]
        ]

    async def get_document_outline(
        self, params: GetDocumentOutlineInput
    ) -> list[DocumentOutlineSection]:
        doc = await verify_user_can_access_document(
            self.session,
            user_id=self.user_id,
            document_id=params.document_id,
            as_of_date=self.as_of_date,
        )
        if doc is None or doc.current_version_id is None:
            return []
        stmt = (
            select(Chunk)
            .where(Chunk.document_version_id == doc.current_version_id)
            .order_by(Chunk.ordinal.asc())
        )
        chunks = list((await self.session.execute(stmt)).scalars().all())
        return [
            DocumentOutlineSection(
                ordinal=c.ordinal,
                section_path=c.section_path,
                page_start=c.page_start,
            )
            for c in chunks
        ]
