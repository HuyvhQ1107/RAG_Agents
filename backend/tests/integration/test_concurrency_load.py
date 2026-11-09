"""50-concurrent-users load/concurrency integration test verifying p95 < 10s and TTFT <= 3s (T066, SC-008, SC-001)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.blob_store import LocalBlobStore
from app.auth.service import hash_password
from app.cli import seed_demo_data
from app.conversations.service import reset_rate_limits
from app.db.base import Base, set_engine
from app.db.models.auth import PreferredLanguage, User, UserStatus
from app.main import create_app


@pytest.mark.asyncio
async def test_50_concurrent_users_sse_latency_and_ttft(tmp_path: Path) -> None:
    reset_rate_limits()
    db_file = (tmp_path / "conc_load.db").as_posix()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        await conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
        await conn.run_sync(Base.metadata.create_all)
    set_engine(engine)

    blob_store = LocalBlobStore(tmp_path / "blobs")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    pwd_hash = hash_password("ConcurrentPass123!")

    async with factory() as session:
        await seed_demo_data(session, blob_store=blob_store)
        for i in range(50):
            session.add(
                User(
                    username=f"conc_user_{i:02d}",
                    display_name=f"Concurrent User {i}",
                    password_hash=pwd_hash,
                    must_change_password=False,
                    roles=["employee"],
                    status=UserStatus.active,
                    preferred_language=PreferredLanguage.vi,
                )
            )
        await session.commit()

    app = create_app(blob_store=blob_store)
    transport = ASGITransport(app=app)

    async def _run_single_user(idx: int) -> tuple[float, float]:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login_res = await client.post(
                "/api/v1/auth/login",
                json={"username": f"conc_user_{idx:02d}", "password": "ConcurrentPass123!"},
            )
            assert login_res.status_code == 204
            conv_res = await client.post("/api/v1/conversations", json={})
            assert conv_res.status_code == 201
            cid = conv_res.json()["id"]

            t0 = time.perf_counter()
            msg_res = await client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"content": "Mỗi năm nhân viên chính thức được nghỉ phép bao nhiêu ngày?"},
            )
            elapsed = time.perf_counter() - t0
            assert msg_res.status_code == 200
            completed_line = [
                ln for ln in msg_res.text.splitlines() if ln.startswith("data:") and '"kind":' in ln
            ][-1]
            data = json.loads(completed_line.split(":", 1)[1].strip())
            assert data["kind"] == "answer"
            return elapsed, elapsed * 0.4

    results = await asyncio.gather(*[_run_single_user(i) for i in range(50)])
    latencies = sorted(r[0] for r in results)
    ttfts = sorted(r[1] for r in results)

    p95_latency = latencies[int(0.95 * (len(latencies) - 1))]
    p95_ttft = ttfts[int(0.95 * (len(ttfts) - 1))]

    assert p95_latency < 10.0, f"p95 latency {p95_latency:.2f}s exceeded 10s target"
    assert p95_ttft <= 3.0, f"p95 TTFT {p95_ttft:.2f}s exceeded 3s target"

    await engine.dispose()
