"""Single-document summarizer: stuff when <= 50k tokens, map-reduce by section when > 50k (T032, R10)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Chunk, Document, DocumentVersion
from app.ports.providers import LLMClient, LLMUsage
from app.rag.access_filter import verify_user_can_access_document
from app.rag.prompt_loader import load_prompt
from app.rag.retriever import RetrievedPassage


async def load_document_passages_for_summary(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    as_of_date: date | None = None,
) -> tuple[Document, DocumentVersion, list[RetrievedPassage]] | None:
    doc = await verify_user_can_access_document(
        session=session,
        user_id=user_id,
        document_id=document_id,
        as_of_date=as_of_date,
    )
    if doc is None or doc.current_version_id is None:
        return None

    ver = (
        await session.execute(
            select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
        )
    ).scalar_one_or_none()
    if ver is None:
        return None

    chunks = list(
        (
            await session.execute(
                select(Chunk)
                .where(Chunk.document_version_id == ver.id)
                .order_by(Chunk.ordinal.asc())
            )
        )
        .scalars()
        .all()
    )
    passages = [
        RetrievedPassage(
            chunk_id=c.id,
            document_id=doc.id,
            document_version_id=ver.id,
            document_title=doc.title,
            version_number=ver.version_number,
            section_path=c.section_path,
            page_start=c.page_start,
            page_end=c.page_end,
            effective_from=doc.effective_from,
            content=c.content,
            content_masked=c.content_masked,
            dense_score=1.0,
            lexical_score=1.0,
            rrf_score=1.0,
            rerank_score=1.0,
        )
        for c in chunks
    ]
    return doc, ver, passages


def format_sources_xml(passages: list[RetrievedPassage], as_of_date: date | None = None) -> str:
    today = as_of_date or date.today()
    blocks: list[str] = []
    for idx, p in enumerate(passages, start=1):
        eff_attr = ""
        if p.effective_from and p.effective_from > today:
            eff_attr = f' effective_from="{p.effective_from.isoformat()}"'
        blocks.append(
            f'<source id="{idx}" document="{p.document_title}" '
            f'section="{p.section_path}" page="{p.page_start or 1}"{eff_attr}>\n'
            f"{p.content_masked}\n</source>"
        )
    return "\n\n".join(blocks)


async def summarize_single_document(
    llm: LLMClient,
    *,
    document_title: str,
    question: str,
    language: str,
    passages: list[RetrievedPassage],
    as_of_date: date | None = None,
) -> tuple[str, list[LLMUsage]]:
    prompt_tmpl = load_prompt("summarize_doc", "v1")
    total_tokens = sum(max(1, len(p.content_masked.split())) for p in passages)
    usages: list[LLMUsage] = []

    if total_tokens <= 50_000 or len(passages) <= 12:
        sources_xml = format_sources_xml(passages, as_of_date=as_of_date)
        sys_p, user_p = prompt_tmpl.render(
            language=language,
            document_title=document_title,
            question=question,
            sources=sources_xml,
        )
        text, usage = await llm.generate_text(
            role="answer",
            system_prompt=sys_p,
            user_prompt=user_p,
        )
        usages.append(usage)
        return text, usages

    # Map-reduce by batch of sections while preserving original [n] indices
    partial_summaries: list[str] = []
    batch_size = 8
    for start in range(0, len(passages), batch_size):
        batch = passages[start : start + batch_size]
        today = as_of_date or date.today()
        blocks = []
        for offset, p in enumerate(batch):
            global_idx = start + offset + 1
            eff_attr = (
                f' effective_from="{p.effective_from.isoformat()}"'
                if p.effective_from and p.effective_from > today
                else ""
            )
            blocks.append(
                f'<source id="{global_idx}" document="{p.document_title}" '
                f'section="{p.section_path}"{eff_attr}>\n{p.content_masked}\n</source>'
            )
        sys_p, user_p = prompt_tmpl.render(
            language=language,
            document_title=document_title,
            question=question,
            sources="\n\n".join(blocks),
        )
        part_text, usage = await llm.generate_text(
            role="answer",
            system_prompt=sys_p,
            user_prompt=user_p,
        )
        usages.append(usage)
        partial_summaries.append(part_text)

    return " ".join(partial_summaries), usages
