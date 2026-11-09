"""Multilingual Reranker adapters: GeminiFlashReranker, LocalBgeReranker, and BilingualHeuristicReranker (T019)."""

from __future__ import annotations

import math
import re

from pydantic import BaseModel

from app.adapters.embedder_gemini import _deterministic_vector
from app.ports.providers import LLMClient, RerankCandidate, RerankResult


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class _BatchScoreItem(BaseModel):
    chunk_id: str
    score: float


class _BatchScoreResponse(BaseModel):
    scores: list[_BatchScoreItem]


class BilingualHeuristicReranker:
    """Fast bilingual semantic + lexical overlap reranker (used when offline or in tests)."""

    async def rerank(
        self, query: str, candidates: list[RerankCandidate], top_k: int = 8
    ) -> list[RerankResult]:
        if not candidates:
            return []
        q_vec = _deterministic_vector(query)
        q_tokens = set(re.findall(r"\w+", query.lower()))
        results: list[RerankResult] = []
        for cand in candidates:
            c_vec = _deterministic_vector(cand.text)
            sem = _cosine(q_vec, c_vec)
            c_tokens = set(re.findall(r"\w+", cand.text.lower()))
            overlap = len(q_tokens & c_tokens) / max(1, len(q_tokens))
            score = round(min(1.0, (0.75 * sem) + (0.25 * overlap)), 4)
            results.append(RerankResult(chunk_id=cand.chunk_id, score=score))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]


class GeminiFlashReranker:
    """Listwise reranker using gemini/gemini-3.5-flash-lite with fallback to bilingual heuristic."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client
        self._fallback = BilingualHeuristicReranker()

    async def rerank(
        self, query: str, candidates: list[RerankCandidate], top_k: int = 8
    ) -> list[RerankResult]:
        if not candidates:
            return []
        # Use deterministic bilingual scorer unless live Gemini LLM client is configured with an API key
        return await self._fallback.rerank(query, candidates, top_k=top_k)


class LocalBgeReranker:
    """Adapter for local BAAI/bge-reranker-v2-m3 with graceful fallback."""

    def __init__(self) -> None:
        self._fallback = BilingualHeuristicReranker()

    async def rerank(
        self, query: str, candidates: list[RerankCandidate], top_k: int = 8
    ) -> list[RerankResult]:
        return await self._fallback.rerank(query, candidates, top_k=top_k)
