"""Deterministic and rubric judges for RAG + Agent evaluation (T062)."""

from __future__ import annotations

import re
from typing import Any

from app.privacy.masker import contains_raw_pii


def check_citation_validity(answer_text: str, citations: list[dict[str, Any]], behavior: str) -> bool:
    """Verify every [n] marker maps to a valid citation item and answer/summary/partial turns have >=1 citation."""
    markers_in_text = [int(m) for m in re.findall(r"\[(\d+)\]", answer_text)]
    if behavior in ("answer", "summary", "partial"):
        if not markers_in_text or not citations:
            return False
    valid_markers = {int(c["marker"]) for c in citations}
    return all(m in valid_markers for m in markers_in_text)


def check_gold_facts(text: str, gold_facts: list[str]) -> float:
    """Compute fraction of required gold facts present in the generated response."""
    if not gold_facts:
        return 1.0
    lower = text.lower()
    matched = sum(1 for fact in gold_facts if fact.lower() in lower)
    return matched / len(gold_facts)


def check_forbidden_substrings(text: str, forbidden: list[str]) -> list[str]:
    """Return any forbidden substrings leaked in the output."""
    lower = text.lower()
    return [sub for sub in forbidden if sub.lower() in lower]


def check_provider_payloads_for_pii(payloads: list[str]) -> int:
    """Count how many external provider payloads leaked raw PII."""
    return sum(1 for p in payloads if contains_raw_pii(p))
