"""Deterministic citation verifier and renumberer (T031, FR-003, FR-003a, SC-003)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.retriever import RetrievedPassage

_MARKER_PATTERN = re.compile(r"\[(\d+)\]")


@dataclass
class VerifiedCitation:
    marker: int
    original_index: int
    passage: RetrievedPassage


@dataclass
class CitationVerificationResult:
    cleaned_answer: str
    citations: list[VerifiedCitation]
    removed_markers: list[int]


def verify_citations(
    raw_answer: str,
    context_passages: list[RetrievedPassage],
) -> CitationVerificationResult:
    """
    Deterministically validate every [n] marker in raw_answer against context_passages (1-indexed).
    - Any [n] outside 1..len(context_passages) is stripped and recorded in removed_markers.
    - Valid markers are renumbered 1..k in order of first appearance so markers are contiguous
      and every listed source is used at least once (FR-003a).
    """
    max_valid = len(context_passages)
    removed_markers: list[int] = []
    old_to_new: dict[int, int] = {}
    ordered_passages: list[ tuple[int, RetrievedPassage] ] = []

    def _replace(match: re.Match[str]) -> str:
        num = int(match.group(1))
        if num < 1 or num > max_valid:
            removed_markers.append(num)
            return ""
        if num not in old_to_new:
            new_marker = len(old_to_new) + 1
            old_to_new[num] = new_marker
            ordered_passages.append((num, context_passages[num - 1]))
        return f"[{old_to_new[num]}]"

    cleaned = _MARKER_PATTERN.sub(_replace, raw_answer)
    # Clean up any double spaces before punctuation caused by stripping invalid markers
    cleaned = re.sub(r"\s+([.,;!?])", r"\1", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned).strip()

    verified = [
        VerifiedCitation(
            marker=idx,
            original_index=orig_idx,
            passage=passage,
        )
        for idx, (orig_idx, passage) in enumerate(ordered_passages, start=1)
    ]

    return CitationVerificationResult(
        cleaned_answer=cleaned,
        citations=verified,
        removed_markers=removed_markers,
    )
