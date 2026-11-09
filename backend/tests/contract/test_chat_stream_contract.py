"""Contract & integration tests for SSE chat stream and single-document scope (T026)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.blob_store import LocalBlobStore
from app.cli import seed_demo_data
from app.conversations.service import reset_rate_limits
from app.db.base import Base, set_engine
from app.main import create_app


def _parse_sse(raw_sse: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw_sse.strip().split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        ev_type = ""
        ev_data: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                ev_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                ev_data = json.loads(line.split(":", 1)[1].strip())
        if ev_type:
            events.append((ev_type, ev_data))
    return events


@pytest.mark.asyncio
async def test_sse_stream_contract_and_bilingual_qa_and_scope(tmp_path: Path) -> None:
    reset_rate_limits()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_engine(engine)

    blob_store = LocalBlobStore(tmp_path / "blobs")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        seeded = await seed_demo_data(session, blob_store=blob_store)
    docs_map = seeded["documents"]

    app = create_app(blob_store=blob_store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as emp_eng
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "emp_eng", "password": "EmployeePass123!"},
        )
        assert resp.status_code == 204
        assert "X-Trace-Id" in resp.headers

        # Create conversation
        conv_resp = await client.post("/api/v1/conversations", json={})
        assert conv_resp.status_code == 201
        conv_id = conv_resp.json()["id"]

        # 1. Vietnamese grounded lookup question
        msg_resp = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Mỗi năm nhân viên chính thức được nghỉ phép bao nhiêu ngày?"},
        )
        assert msg_resp.status_code == 200
        assert msg_resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(msg_resp.text)
        event_names = [e[0] for e in events]

        assert event_names[0] == "turn.started"
        assert "status" in event_names
        assert "answer.delta" in event_names
        assert "citations" in event_names
        assert event_names[-1] == "turn.completed"

        full_text = "".join(d["text"] for name, d in events if name == "answer.delta")
        assert "12 ngày" in full_text
        assert "[1]" in full_text

        cit_event = next(d for name, d in events if name == "citations")
        assert len(cit_event["items"]) >= 1
        assert cit_event["items"][0]["marker"] == 1
        assert cit_event["items"][0]["document_title"] == "Quy định nghỉ phép"

        # Verify citation detail endpoint & file download
        cit_id = cit_event["items"][0]["citation_id"]
        cit_detail = await client.get(f"/api/v1/citations/{cit_id}")
        assert cit_detail.status_code == 200
        assert "12 ngày" in cit_detail.json()["full_content"]

        # 2. Cross-lingual English question on Vietnamese source document
        en_resp = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "How many annual leave days do full-time employees get?"},
        )
        en_events = _parse_sse(en_resp.text)
        en_completed = en_events[-1][1]
        assert en_completed["kind"] == "answer"
        assert en_completed["answer_language"] == "en"
        en_text = "".join(d["text"] for name, d in en_events if name == "answer.delta")
        assert "12" in en_text and "[1]" in en_text

        # 3. Single-document scope selection (FR-009c): scope to "Sổ tay nhân viên" and ask about leave -> not found in selected document
        handbook_id = docs_map["Sổ tay nhân viên"]
        patch_resp = await client.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"scope_document_id": handbook_id},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["scope_document_id"] == handbook_id

        scoped_resp = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Số ngày nghỉ phép năm của nhân viên chính thức là bao nhiêu?"},
        )
        scoped_events = _parse_sse(scoped_resp.text)
        assert scoped_events[-1][1]["kind"] == "refusal_not_found"

        # 4. Unsupported corpus-wide aggregation (FR-009b)
        agg_resp = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Liệt kê tất cả các chính sách phúc lợi của toàn bộ tài liệu công ty"},
        )
        agg_events = _parse_sse(agg_resp.text)
        assert agg_events[-1][1]["kind"] == "refusal_unsupported"

    await engine.dispose()
