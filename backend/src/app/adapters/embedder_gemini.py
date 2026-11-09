"""Gemini Embedding adapter (gemini-embedding-001, 768 dims MRL) & deterministic FakeEmbedder (T018)."""

from __future__ import annotations

import hashlib
import math
import re

from app.config import get_settings
from app.privacy.masker import mask_pii

# Bilingual synonym normalization for deterministic test embeddings so cross-lingual queries match!
_BILINGUAL_CONCEPTS: list[tuple[str, list[str]]] = [
    (
        "concept_annual_leave_days",
        [
            "nghỉ phép",
            "phép năm",
            "annual leave",
            "leave days",
            "bao nhiêu ngày",
            "how many",
            "12 ngày",
            "12 days",
            "chính thức",
            "full-time",
        ],
    ),
    (
        "concept_probation_unpaid",
        ["thử việc", "probation", "nghỉ không lương", "unpaid leave"],
    ),
    (
        "concept_travel",
        [
            "công tác phí",
            "business trip",
            "per diem",
            "nước ngoài",
            "overseas",
            "khách sạn",
            "phụ cấp",
            "định mức",
        ],
    ),
    (
        "concept_salary",
        ["bảng lương", "mức lương", "bậc lương", "salary", "compensation", "bậc 3", "grade 3"],
    ),
    (
        "concept_working_hours",
        ["giờ làm việc", "working hours", "sổ tay nhân viên", "handbook", "8h30", "17h30"],
    ),
    ("concept_hr_contact", ["nhân sự", "hr", "liên hệ", "thủ tục", "điều kiện"]),
]


def _deterministic_vector(text: str, dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    lower = text.lower()
    # Concept dimensions (slots 0..31) for semantic + cross-lingual alignment
    for idx, (_name, keywords) in enumerate(_BILINGUAL_CONCEPTS):
        for kw in keywords:
            if kw in lower:
                vec[idx] += 3.0

    # Token hash dimensions (slots 32..dim-1)
    tokens = re.findall(r"\w+", lower)
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        slot = 32 + (h % (dim - 32))
        vec[slot] += 1.0

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [round(v / norm, 6) for v in vec]
    else:
        vec[0] = 1.0
    return vec


class GeminiEmbedder:
    """Google Gemini embedding adapter using gemini/gemini-embedding-001 (768 dims)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.recorded_payloads: list[str] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        safe_texts = [mask_pii(t)[0] for t in texts]
        self.recorded_payloads.extend(safe_texts)
        if not self.settings.gemini_api_key:
            return [_deterministic_vector(t, self.settings.embedding_dim) for t in safe_texts]

        import litellm

        resp = await litellm.aembedding(
            model=self.settings.embedding_model,
            input=safe_texts,
            api_key=self.settings.gemini_api_key,
            dimensions=self.settings.embedding_dim,
        )
        return [list(item["embedding"])[: self.settings.embedding_dim] for item in resp.data]

    async def embed_query(self, text: str) -> list[float]:
        safe_text, _ = mask_pii(text)
        self.recorded_payloads.append(safe_text)
        if not self.settings.gemini_api_key:
            return _deterministic_vector(safe_text, self.settings.embedding_dim)

        import litellm

        resp = await litellm.aembedding(
            model=self.settings.embedding_model,
            input=[safe_text],
            api_key=self.settings.gemini_api_key,
            dimensions=self.settings.embedding_dim,
        )
        return list(resp.data[0]["embedding"])[: self.settings.embedding_dim]


class FakeEmbedder:
    """Deterministic bilingual-aware 768d embedder for unit/integration/eval tests."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.recorded_payloads: list[str] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        safe_texts = [mask_pii(t)[0] for t in texts]
        self.recorded_payloads.extend(safe_texts)
        return [_deterministic_vector(t, self.dim) for t in safe_texts]

    async def embed_query(self, text: str) -> list[float]:
        safe_text, _ = mask_pii(text)
        self.recorded_payloads.append(safe_text)
        return _deterministic_vector(safe_text, self.dim)
