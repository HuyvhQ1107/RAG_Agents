"""Unit tests for deterministic citation verifier and Reciprocal Rank Fusion (T025)."""

from __future__ import annotations

import uuid

from app.rag.citation_verifier import verify_citations
from app.rag.retriever import RetrievedPassage, reciprocal_rank_fusion


def _make_passage(title: str, section: str) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        document_title=title,
        version_number=1,
        section_path=section,
        page_start=1,
        page_end=1,
        effective_from=None,
        content=f"Content of {title} {section}",
        content_masked=f"Content of {title} {section}",
        dense_score=0.9,
        lexical_score=0.8,
        rrf_score=0.03,
        rerank_score=0.88,
    )


def test_rrf_combines_dense_and_lexical_rankings() -> None:
    dense = ["c1", "c2", "c3"]
    lexical = ["c2", "c4", "c1"]
    fused = reciprocal_rank_fusion([dense, lexical], k=60, top_n=4)
    ids = [cid for cid, _ in fused]
    # c1 and c2 appear in both lists, so they must rank above c3 and c4
    assert set(ids[:2]) == {"c1", "c2"}
    assert len(fused) == 4


def test_verify_citations_strips_invalid_markers_and_renumbers_contiguously() -> None:
    p1 = _make_passage("Quy định nghỉ phép", "Điều 5")
    p2 = _make_passage("Quy định nghỉ phép", "Điều 6")
    p3 = _make_passage("Sổ tay nhân viên", "Phần 1")

    # LLM cites [3] first, then [1], never cites [2], and hallucinates [99] and [0]
    raw_answer = (
        "Giờ làm việc từ 8h30 đến 17h30 [3] [99]. "
        "Nhân viên chính thức có 12 ngày phép năm [1] [0]."
    )
    res = verify_citations(raw_answer, [p1, p2, p3])

    assert res.removed_markers == [99, 0]
    assert "[99]" not in res.cleaned_answer
    assert "[0]" not in res.cleaned_answer
    # [3] becomes [1], [1] becomes [2], and unused p2 is omitted from citations list
    assert res.cleaned_answer == (
        "Giờ làm việc từ 8h30 đến 17h30 [1]. "
        "Nhân viên chính thức có 12 ngày phép năm [2]."
    )
    assert len(res.citations) == 2
    assert res.citations[0].marker == 1
    assert res.citations[0].passage.document_title == "Sổ tay nhân viên"
    assert res.citations[1].marker == 2
    assert res.citations[1].passage.section_path == "Điều 5"
