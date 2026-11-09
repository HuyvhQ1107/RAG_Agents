"""Unit and integration tests for document parser, structural chunker, and atomic version promotion (T050)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.blob_store import LocalBlobStore
from app.adapters.embedder_gemini import FakeEmbedder
from app.cli import seed_demo_data
from app.db.base import Base
from app.db.models.auth import User
from app.db.models.document import Chunk, Document, DocumentVersion, DocumentVersionStatus
from app.documents.admin_service import upload_documents_admin, upload_new_version_admin
from app.documents.chunker import chunk_parsed_document
from app.documents.parser import DocumentParseError, parse_document_bytes


def test_parser_rejects_encrypted_and_scanned_pdf_and_parses_markdown_tables() -> None:
    # Encrypted PDF marker -> encrypted_unsupported
    with pytest.raises(DocumentParseError) as exc_info:
        parse_document_bytes("secret.pdf", b"%PDF-1.7\n/Encrypt << >>\n%%EOF")
    assert exc_info.value.error_code == "encrypted_unsupported"

    # Encrypted Office OLE2 header -> encrypted_unsupported
    with pytest.raises(DocumentParseError) as exc_info2:
        parse_document_bytes("locked.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert exc_info2.value.error_code == "encrypted_unsupported"

    # Markdown with headings & pipe table -> structural chunks preserve section_path and table kind
    md = (
        "# Chương 1: Quy định chung\n\n"
        "## Điều 1: Phạm vi áp dụng\n\n"
        "Quy định này áp dụng cho toàn bộ nhân viên chính thức của công ty.\n\n"
        "| Cấp bậc | Phụ cấp |\n"
        "| --- | --- |\n"
        "| Bậc 1 | 1.000.000 VNĐ |\n"
        "| Bậc 2 | 2.000.000 VNĐ |\n"
    ).encode()
    mime, parsed = parse_document_bytes("policy.md", md)
    assert mime == "text/markdown"
    chunks = chunk_parsed_document(parsed)
    assert len(chunks) == 2
    assert "Chương 1" in chunks[0].section_path and "Điều 1" in chunks[0].section_path
    assert chunks[1].kind.value == "table"
    assert "| Cấp bậc | Phụ cấp |" in chunks[1].content


@pytest.mark.asyncio
async def test_atomic_version_promotion_and_duplicate_sha_rejection(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    blob_store = LocalBlobStore(tmp_path / "blobs")
    embedder = FakeEmbedder()

    async with factory() as session:
        await seed_demo_data(session, blob_store=blob_store, embedder=embedder)
        admin_user = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()

        v1_bytes = (
            "# Quy định làm việc từ xa\n\n"
            "## Điều 1\n\n"
            "Phiên bản 1: Nhân viên được làm việc từ xa 2 ngày/tháng. Liên hệ SĐT 0987654321."
        ).encode()

        created = await upload_documents_admin(
            session,
            uploaded_by=admin_user.id,
            files=[("Remote_Work.md", v1_bytes)],
            group_ids=[],
            is_company_wide=True,
            blob_store=blob_store,
            embedder=embedder,
            run_inline=True,
        )
        assert len(created) == 1
        assert created[0]["status"] == "ready"
        doc_id = uuid.UUID(created[0]["document_id"])
        v1_id = uuid.UUID(created[0]["version_id"])

        # Verify PII was masked in chunks.content_masked and embedder payload
        v1_chunks = list(
            (
                await session.execute(
                    select(Chunk).where(Chunk.document_version_id == v1_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(v1_chunks) == 1
        assert "0987654321" in v1_chunks[0].content
        assert "0987654321" not in v1_chunks[0].content_masked
        assert "<PHONE_1>" in v1_chunks[0].content_masked

        # Upload v2 -> v2 becomes current_version_id and v1 becomes superseded atomically
        v2_bytes = (
            "# Quy định làm việc từ xa\n\n"
            "## Điều 1\n\n"
            "Phiên bản 2 (Mới): Nhân viên được làm việc từ xa 4 ngày/tháng."
        ).encode()
        v2_res = await upload_new_version_admin(
            session,
            document_id=doc_id,
            uploaded_by=admin_user.id,
            filename="Remote_Work_v2.md",
            raw_bytes=v2_bytes,
            blob_store=blob_store,
            embedder=embedder,
            run_inline=True,
        )
        assert v2_res["version_number"] == 2
        assert v2_res["status"] == "ready"

        doc_row = (
            await session.execute(select(Document).where(Document.id == doc_id))
        ).scalar_one()
        assert str(doc_row.current_version_id) == v2_res["version_id"]

        v1_row = (
            await session.execute(select(DocumentVersion).where(DocumentVersion.id == v1_id))
        ).scalar_one()
        assert v1_row.status == DocumentVersionStatus.superseded

    await engine.dispose()
