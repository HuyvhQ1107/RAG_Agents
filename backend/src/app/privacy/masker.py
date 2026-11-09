"""Reversible PII masking with Presidio + Vietnamese custom recognizers (T015, FR-020, FR-021, SC-011)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Vietnamese & general PII patterns ordered from most specific to least specific
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "BANK_ACCOUNT",
        re.compile(
            r"\b(?:stk|số\s+tài\s+khoản|account(?:\s*no\.?)?)\s*[:\-]?\s*(\d{8,19})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "SALARY",
        re.compile(
            r"\b(?:mức\s+lương|lương\s+cơ\s+bản|lương|thu\s+nhập|salary)\s*[:\-]?\s*"
            r"(\d{1,3}(?:[.,]\d{3})+(?:\s*(?:vnđ|vnd|đồng|usd|\$))?|\d+\s*(?:triệu|tr|million)(?:\s*(?:vnđ|vnd|đồng))?)",
            re.IGNORECASE,
        ),
    ),
    (
        "CCCD",
        re.compile(r"\b0\d{11}\b"),
    ),
    (
        "PASSPORT",
        re.compile(r"\b[BCEG]\d{7,8}\b"),
    ),
    (
        "PHONE",
        re.compile(r"(?:\+84|84|0)(?:3|5|7|8|9)\d{8}\b"),
    ),
    (
        "CMND",
        re.compile(
            r"(?:cmnd|chứng\s+minh\s+nhân\s+dân)\s*[:\-]?\s*(\d{9})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "SECRET",
        re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z\-_]{30,})\b"),
    ),
]


@dataclass
class PIIMaskingSession:
    """Per-request reversible PII masking map (never persisted to logs/DB)."""

    placeholder_to_raw: dict[str, str] = field(default_factory=dict)
    raw_to_placeholder: dict[str, str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def _get_or_create_placeholder(self, pii_type: str, raw_value: str) -> str:
        existing = self.raw_to_placeholder.get(raw_value)
        if existing:
            return existing
        idx = self.counters.get(pii_type, 0) + 1
        self.counters[pii_type] = idx
        placeholder = f"<{pii_type}_{idx}>"
        self.raw_to_placeholder[raw_value] = placeholder
        self.placeholder_to_raw[placeholder] = raw_value
        return placeholder

    def mask(self, text: str) -> str:
        if not text:
            return text
        masked = text
        for pii_type, pattern in _PII_PATTERNS:
            def _repl(match: re.Match[str], _t: str = pii_type) -> str:
                # If a capturing group matched the sensitive value specifically, replace only that span
                if match.lastindex:
                    full = match.group(0)
                    sensitive = match.group(match.lastindex)
                    ph = self._get_or_create_placeholder(_t, sensitive)
                    start_rel = match.start(match.lastindex) - match.start(0)
                    end_rel = match.end(match.lastindex) - match.start(0)
                    return full[:start_rel] + ph + full[end_rel:]
                raw = match.group(0)
                return self._get_or_create_placeholder(_t, raw)

            masked = pattern.sub(_repl, masked)
        return masked

    def unmask(self, text: str) -> str:
        if not text or not self.placeholder_to_raw:
            return text
        restored = text
        for placeholder, raw in self.placeholder_to_raw.items():
            restored = restored.replace(placeholder, raw)
        return restored


def mask_pii(text: str, session: PIIMaskingSession | None = None) -> tuple[str, PIIMaskingSession]:
    """Mask PII in text and return (masked_text, session)."""
    active = session or PIIMaskingSession()
    return active.mask(text), active


def contains_raw_pii(text: str) -> bool:
    """Deterministic check used by tests and eval runner (SC-011)."""
    if not text:
        return False
    for _, pattern in _PII_PATTERNS:
        if pattern.search(text):
            return True
    return False
