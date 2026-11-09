"""Integration tests for 100% SQL access-control pre-filtering, immediate revocation, soft-deleted group orphans, and effective/expiry dates (T038)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.blob_store import LocalBlobStore
from app.auth.admin_service import soft_delete_group_admin, update_user_admin
from app.cli import seed_demo_data
from app.conversations.service import reset_rate_limits
from app.db.base import Base, set_engine
from app.db.models.auth import Group, User
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
async def test_department_access_control_prefilter_and_revocation_and_lifecycle(
    tmp_path: Path,
) -> None:
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
    salary_doc_id = docs_map["Bảng lương 2026"]

    app = create_app(blob_store=blob_store)
    transport = ASGITransport(app=app)

    # 1. emp_eng (Engineering) asks about HR-only "Bảng lương 2026" -> MUST be refusal_not_found with 0 leaked chunks
    async with AsyncClient(transport=transport, base_url="http://test") as eng_client:
        await eng_client.post(
            "/api/v1/auth/login",
            json={"username": "emp_eng", "password": "EmployeePass123!"},
        )
        # Direct document download or scope setting on unauthorized doc returns 404 (FR-018)
        dl_resp = await eng_client.get(f"/api/v1/documents/{salary_doc_id}/file")
        assert dl_resp.status_code == 404

        conv_id = (await eng_client.post("/api/v1/conversations", json={})).json()["id"]
        ans_resp = await eng_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Mức lương bậc 3 trong bảng lương 2026 là bao nhiêu?"},
        )
        events = _parse_sse(ans_resp.text)
        assert events[-1][1]["kind"] == "refusal_not_found"
        text = "".join(d["text"] for name, d in events if name == "answer.delta")
        assert "38.000.000" not in text
        assert "Bảng lương 2026" not in text

        # Expired document ("Quy định hỗ trợ gửi xe 2024 (Cũ)") must NEVER be used as source (FR-025a)
        exp_resp = await eng_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Phụ cấp hỗ trợ phí gửi xe năm 2024 là bao nhiêu?"},
        )
        exp_events = _parse_sse(exp_resp.text)
        exp_text = "".join(d["text"] for name, d in exp_events if name == "answer.delta")
        assert "150.000" not in exp_text

        # Scheduled future document ("Quy định công tác phí") MUST include "áp dụng từ ngày" (FR-025a)
        sched_resp = await eng_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Định mức công tác phí trong nước và nước ngoài là bao nhiêu?"},
        )
        sched_events = _parse_sse(sched_resp.text)
        sched_text = "".join(d["text"] for name, d in sched_events if name == "answer.delta")
        assert "áp dụng từ ngày" in sched_text

    # 2. emp_hr (HR) asks the exact same salary question -> MUST get answer with citation
    async with AsyncClient(transport=transport, base_url="http://test") as hr_client:
        await hr_client.post(
            "/api/v1/auth/login",
            json={"username": "emp_hr", "password": "EmployeePass123!"},
        )
        conv_id = (await hr_client.post("/api/v1/conversations", json={})).json()["id"]
        hr_resp = await hr_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Mức lương bậc 3 trong bảng lương 2026 là bao nhiêu?"},
        )
        hr_events = _parse_sse(hr_resp.text)
        assert hr_events[-1][1]["kind"] == "answer"
        hr_cits = next(d for name, d in hr_events if name == "citations")["items"]
        assert hr_cits[0]["document_title"] == "Bảng lương 2026"
        salary_citation_id = hr_cits[0]["citation_id"]

        # 3. Revoke emp_hr's HR group membership -> next question & citation view immediately lose access (FR-019)
        async with factory() as session:
            hr_user = (
                await session.execute(select(User).where(User.username == "emp_hr"))
            ).scalar_one()
            await update_user_admin(session, user_id=hr_user.id, group_ids=[])

        cit_after_revoke = await hr_client.get(f"/api/v1/citations/{salary_citation_id}")
        assert cit_after_revoke.status_code == 404

        hr_after_resp = await hr_client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Mức lương bậc 3 trong bảng lương 2026 là bao nhiêu?"},
        )
        hr_after_events = _parse_sse(hr_after_resp.text)
        assert hr_after_events[-1][1]["kind"] == "refusal_not_found"

    # 4. Soft-deleting the HR group MUST NOT make "Bảng lương 2026" company-wide; it becomes orphaned (FR-016a)
    async with factory() as session:
        hr_group = (
            await session.execute(select(Group).where(Group.name == "Nhân sự"))
        ).scalar_one()
        del_res = await soft_delete_group_admin(session, group_id=hr_group.id)
        assert uuid.UUID(salary_doc_id).hex in [
            uuid.UUID(oid).hex for oid in del_res["orphaned_document_ids"]
        ]

    await engine.dispose()
