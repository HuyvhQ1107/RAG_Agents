"""Hybrid Retriever (Dense + Lexical FTS + RRF k=60 + Multilingual Rerank) with SQL pre-filter (T030, T039)."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.document import Chunk, Document, DocumentVersion
from app.ports.providers import Embedder, RerankCandidate, Reranker
from app.rag.access_filter import build_accessible_documents_predicate


def _cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _lexical_score(query: str, target_text: str) -> float:
    q_tokens = [t for t in re.findall(r"\w+", query.lower()) if len(t) >= 2]
    if not q_tokens:
        return 0.0
    t_lower = target_text.lower()
    t_tokens = set(re.findall(r"\w+", t_lower))
    matched = sum(1 for tok in q_tokens if tok in t_tokens or tok in t_lower)
    return matched / len(q_tokens)


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]], k: int = 60, top_n: int = 30
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion (RRF) with constant k=60."""
    scores: dict[str, float] = {}
    for r_list in ranked_lists:
        for rank_idx, item_id in enumerate(r_list, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank_idx))
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return ordered[:top_n]


@dataclass
class RetrievedPassage:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    document_title: str
    version_number: int
    section_path: str
    page_start: int | None
    page_end: int | None
    effective_from: date | None
    content: str
    content_masked: str
    dense_score: float
    lexical_score: float
    rrf_score: float
    rerank_score: float


class HybridRetriever:
    """Executes SQL pre-filtered dense + lexical retrieval, RRF fusion, and multilingual reranking."""

    def __init__(self, embedder: Embedder, reranker: Reranker) -> None:
        self.embedder = embedder
        self.reranker = reranker
        self.settings = get_settings()

    async def search(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        queries: list[str],
        scope_document_id: uuid.UUID | None = None,
        as_of_date: date | None = None,
        top_k: int = 8,
    ) -> list[RetrievedPassage]:
        clean_queries = [q.strip() for q in queries if q and q.strip()]
        if not clean_queries:
            return []

        # Mandatory SQL pre-filter: only active, non-expired current_version chunks user has permission to read
        stmt = (
            select(Chunk, Document, DocumentVersion)
            .join(Document, Document.current_version_id == Chunk.document_version_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .where(
                build_accessible_documents_predicate(
                    user_id=user_id,
                    as_of_date=as_of_date,
                    scope_document_id=scope_document_id,
                )
            )
        )
        rows = (await session.execute(stmt)).all()
        if not rows:
            return []

        row_by_id: dict[str, tuple[Chunk, Document, DocumentVersion]] = {
            str(chunk.id): (chunk, doc, ver) for chunk, doc, ver in rows
        }

        ranked_lists: list[list[str]] = []
        best_dense: dict[str, float] = {}
        best_lex: dict[str, float] = {}

        for q in clean_queries[:4]:
            q_vec = await self.embedder.embed_query(q)
            dense_scored: list[tuple[str, float]] = []
            lex_scored: list[tuple[str, float]] = []

            for cid, (chunk, doc, _ver) in row_by_id.items():
                d_sim = _cosine_similarity(q_vec, chunk.embedding)
                best_dense[cid] = max(best_dense.get(cid, 0.0), d_sim)
                dense_scored.append((cid, d_sim))

                haystack = f"{doc.title} {chunk.section_path} {chunk.content_masked}"
                l_sim = _lexical_score(q, haystack)
                best_lex[cid] = max(best_lex.get(cid, 0.0), l_sim)
                if l_sim > 0:
                    lex_scored.append((cid, l_sim))

            dense_scored.sort(key=lambda x: x[1], reverse=True)
            lex_scored.sort(key=lambda x: x[1], reverse=True)

            ranked_lists.append([cid for cid, _ in dense_scored[:40]])
            if lex_scored:
                ranked_lists.append([cid for cid, _ in lex_scored[:40]])

        fused = reciprocal_rank_fusion(ranked_lists, k=60, top_n=30)
        rrf_map = dict(fused)

        candidates: list[RerankCandidate] = []
        for cid, rrf_val in fused:
            chunk, doc, _ver = row_by_id[cid]
            candidates.append(
                RerankCandidate(
                    chunk_id=cid,
                    text=f"{doc.title} — {chunk.section_path}: {chunk.content_masked}",
                    initial_score=rrf_val,
                )
            )

        primary_query = " | ".join(clean_queries[:2])
        reranked = await self.reranker.rerank(primary_query, candidates, top_k=top_k)

        passages: list[RetrievedPassage] = []
        for item in reranked:
            if item.score < self.settings.rerank_min_score:
                continue
            chunk, doc, ver = row_by_id[item.chunk_id]
            passages.append(
                RetrievedPassage(
                    chunk_id=chunk.id,
                    document_id=doc.id,
                    document_version_id=ver.id,
                    document_title=doc.title,
                    version_number=ver.version_number,
                    section_path=chunk.section_path,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    effective_from=doc.effective_from,
                    content=chunk.content,
                    content_masked=chunk.content_masked,
                    dense_score=round(best_dense.get(item.chunk_id, 0.0), 4),
                    lexical_score=round(best_lex.get(item.chunk_id, 0.0), 4),
                    rrf_score=round(rrf_map.get(item.chunk_id, 0.0), 5),
                    rerank_score=round(item.score, 4),
                )
            )

        return passages
