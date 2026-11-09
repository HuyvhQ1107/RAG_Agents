"""Integration tests for feedback submission (owner check, PII masking) and operator trace/metrics endpoints (T056)."""

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
from app.privacy.masker import contains_raw_pii


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
async def test_feedback_pii_masking_and_operator_trace_inspection(tmp_path: Path) -> None:
    reset_rate_limits()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_engine(engine)

    blob_store = LocalBlobStore(tmp_path / "blobs")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed_demo_data(session, blob_store=blob_store)

    app = create_app(blob_store=blob_store)
    transport = ASGITransport(app=app)

    # 1. Employee asks a question containing PII and submits negative feedback with PII in comment
    async with AsyncClient(transport=transport, base_url="http://test") as emp_client:
        await emp_client.post(
            "/api/v1/auth/login",
            json={"username": "emp_eng", "password": "EmployeePass123!"},
        )
        conv_id = (await emp_client.post("/api/v1/conversations", json={})).json()["id"]
        msg_resp = await emp_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={
                "content": "CCCD của tôi là 079099001234, cho hỏi mỗi năm nhân viên chính thức được nghỉ phép bao nhiêu ngày?"
            },
        )
        events = _parse_sse(msg_resp.text)
        turn_id = events[0][1]["turn_id"]

        fb_resp = await emp_client.put(
            f"/api/v1/turns/{turn_id}/feedback",
            json={
                "rating": "not_helpful",
                "comment": "Câu trả lời thiếu số điện thoại của tôi 0912345678",
            },
        )
        assert fb_resp.status_code == 200
        assert "0912345678" not in (fb_resp.json()["comment"] or "")
        assert "<PHONE_1>" in (fb_resp.json()["comment"] or "")

        # Employee cannot access /api/v1/ops/*
        ops_denied = await emp_client.get("/api/v1/ops/metrics/summary")
        assert ops_denied.status_code == 404

    # 2. Admin / Operator inspects metrics summary, negative feedback list, and turn trace (all PII masked)
    async with AsyncClient(transport=transport, base_url="http://test") as admin_client:
        await admin_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "AdminPassword123!"},
        )
        summary_resp = await admin_client.get("/api/v1/ops/metrics/summary")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        assert summary["total_turns"] >= 1
        assert summary["total_feedback_count"] == 1

        fb_list_resp = await admin_client.get("/api/v1/ops/feedback?rating=not_helpful")
        assert fb_list_resp.status_code == 200
        fb_items = fb_list_resp.json()["items"]
        assert len(fb_items) == 1
        assert not contains_raw_pii(json.dumps(fb_items, ensure_ascii=False))

        trace_resp = await admin_client.get(f"/api/v1/ops/turns/{turn_id}/trace")
        assert trace_resp.status_code == 200
        trace_payload = trace_resp.json()
        trace_str = json.dumps(trace_payload, ensure_ascii=False)
        assert "079099001234" not in trace_str
        assert "0912345678" not in trace_str
        assert not contains_raw_pii(trace_str)

    await engine.dispose()
