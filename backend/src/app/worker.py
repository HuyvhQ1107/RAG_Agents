"""Procrastinate / background worker entrypoint (T053, T063)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.adapters.blob_store import LocalBlobStore
from app.adapters.embedder_gemini import GeminiEmbedder
from app.db.base import get_session_factory
from app.db.models.document import DocumentVersion, DocumentVersionStatus
from app.documents.ingestion_job import (
    cleanup_superseded_chunks,
    ingest_document_version,
    purge_old_conversations,
)


async def process_pending_ingestion_queue() -> int:
    factory = get_session_factory()
    blob_store = LocalBlobStore()
    embedder = GeminiEmbedder()
    processed = 0
    async with factory() as session:
        queued_ids = list(
            (
                await session.execute(
                    select(DocumentVersion.id)
                    .where(DocumentVersion.status == DocumentVersionStatus.queued)
                    .order_by(DocumentVersion.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        for vid in queued_ids:
            await ingest_document_version(
                session, version_id=vid, blob_store=blob_store, embedder=embedder
            )
            processed += 1
    return processed


async def run_worker_loop(poll_seconds: float = 2.0) -> None:
    factory = get_session_factory()
    while True:
        await process_pending_ingestion_queue()
        async with factory() as session:
            await cleanup_superseded_chunks(session)
            await purge_old_conversations(session)
        await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
