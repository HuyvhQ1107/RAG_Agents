"""Structure-aware heading & table chunker (300–700 tokens, ~15% overlap, table header preservation) (T052, R7)."""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models.document import ChunkKind
from app.documents.parser import ParsedDocument


@dataclass
class StructuralChunk:
    ordinal: int
    section_path: str
    page_start: int | None
    page_end: int | None
    content: str
    kind: ChunkKind
    token_count: int


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _split_long_text_with_overlap(
    text: str, target_max_tokens: int = 550, overlap_ratio: float = 0.15
) -> list[str]:
    words = text.split()
    if len(words) <= target_max_tokens:
        return [text]
    overlap = max(10, int(target_max_tokens * overlap_ratio))
    step = max(1, target_max_tokens - overlap)
    parts: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + target_max_tokens)
        parts.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += step
    return parts


def _split_large_table(table_md: str, max_table_tokens: int = 1000) -> list[str]:
    if _estimate_tokens(table_md) <= max_table_tokens:
        return [table_md]
    lines = [ln for ln in table_md.splitlines() if ln.strip()]
    if len(lines) <= 2:
        return [table_md]
    header_lines = lines[:2] if "---" in lines[1] else lines[:1]
    body_lines = lines[len(header_lines) :]
    header_tokens = _estimate_tokens("\n".join(header_lines))
    budget = max(50, max_table_tokens - header_tokens)

    chunks: list[str] = []
    current_rows: list[str] = []
    current_tok = 0
    for row in body_lines:
        rtok = _estimate_tokens(row)
        if current_rows and current_tok + rtok > budget:
            chunks.append("\n".join([*header_lines, *current_rows]))
            current_rows = [row]
            current_tok = rtok
        else:
            current_rows.append(row)
            current_tok += rtok
    if current_rows:
        chunks.append("\n".join([*header_lines, *current_rows]))
    return chunks


def chunk_parsed_document(
    parsed: ParsedDocument,
    *,
    min_tokens: int = 300,
    max_tokens: int = 700,
    overlap_ratio: float = 0.15,
    max_table_tokens: int = 1000,
) -> list[StructuralChunk]:
    heading_stack: dict[int, str] = {}
    output: list[StructuralChunk] = []

    buffer_texts: list[str] = []
    buffer_tokens = 0
    buffer_page_start: int | None = None
    buffer_page_end: int | None = None
    current_section_path = "Tổng quan"

    def _current_path() -> str:
        if not heading_stack:
            return "Tổng quan"
        ordered = [heading_stack[k] for k in sorted(heading_stack.keys())]
        return " > ".join(ordered)

    def _flush_buffer() -> None:
        nonlocal buffer_texts, buffer_tokens, buffer_page_start, buffer_page_end
        if not buffer_texts:
            return
        combined = "\n\n".join(buffer_texts).strip()
        if combined:
            for piece in _split_long_text_with_overlap(
                combined, target_max_tokens=max_tokens, overlap_ratio=overlap_ratio
            ):
                output.append(
                    StructuralChunk(
                        ordinal=len(output) + 1,
                        section_path=current_section_path,
                        page_start=buffer_page_start,
                        page_end=buffer_page_end,
                        content=piece,
                        kind=ChunkKind.text,
                        token_count=_estimate_tokens(piece),
                    )
                )
        buffer_texts = []
        buffer_tokens = 0
        buffer_page_start = None
        buffer_page_end = None

    for block in parsed.blocks:
        if block.kind == "heading":
            _flush_buffer()
            lvl = max(1, block.heading_level or 1)
            for k in [k for k in heading_stack if k >= lvl]:
                del heading_stack[k]
            heading_stack[lvl] = block.text.strip()
            current_section_path = _current_path()
            continue

        if block.kind == "table":
            _flush_buffer()
            for tbl_part in _split_large_table(block.text, max_table_tokens=max_table_tokens):
                output.append(
                    StructuralChunk(
                        ordinal=len(output) + 1,
                        section_path=current_section_path,
                        page_start=block.page,
                        page_end=block.page,
                        content=tbl_part,
                        kind=ChunkKind.table,
                        token_count=_estimate_tokens(tbl_part),
                    )
                )
            continue

        # Paragraph
        btok = _estimate_tokens(block.text)
        if buffer_tokens >= min_tokens and (buffer_tokens + btok) > max_tokens:
            _flush_buffer()

        if buffer_page_start is None:
            buffer_page_start = block.page
        buffer_page_end = block.page
        buffer_texts.append(block.text)
        buffer_tokens += btok

    _flush_buffer()
    return output
