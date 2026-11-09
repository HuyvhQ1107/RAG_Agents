"""Provider ports for LLM, Embedding, Reranking, and Blob Storage (T016, Constitution VII)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


@dataclass
class LLMUsage:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


@dataclass
class LLMStreamResult:
    stream: AsyncIterator[str]
    usage: LLMUsage


class LLMClient(Protocol):
    async def generate_structured(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        temperature: float = 0.0,
    ) -> tuple[TModel, LLMUsage]: ...

    async def generate_text(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> tuple[str, LLMUsage]: ...

    def stream_text(
        self,
        *,
        role: Literal["fast", "answer"],
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> tuple[AsyncIterator[str], LLMUsage]: ...


class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


@dataclass
class RerankCandidate:
    chunk_id: str
    text: str
    initial_score: float = 0.0


@dataclass
class RerankResult:
    chunk_id: str
    score: float


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[RerankCandidate], top_k: int = 8
    ) -> list[RerankResult]: ...


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> str: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...
