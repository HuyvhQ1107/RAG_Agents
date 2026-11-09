"""CLI commands including seed-demo for standalone story testing (T022)."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.blob_store import LocalBlobStore
from app.adapters.embedder_gemini import FakeEmbedder
from app.auth.service import hash_password
from app.db.base import Base, get_engine, get_session_factory, utcnow
from app.db.models.auth import Group, PreferredLanguage, User, UserGroup, UserStatus
from app.db.models.document import (
    Chunk,
    ChunkKind,
    Document,
    DocumentGroup,
    DocumentLanguage,
    DocumentStatus,
    DocumentVersion,
    DocumentVersionStatus,
)
from app.privacy.masker import mask_pii


async def seed_demo_data(
    session: AsyncSession,
    blob_store: LocalBlobStore | None = None,
    embedder: FakeEmbedder | None = None,
) -> dict[str, Any]:
    """Seed users, groups, and sample bilingual documents/chunks idempotently."""
    store = blob_store or LocalBlobStore()
    emb = embedder or FakeEmbedder()

    # Check if already seeded
    existing = (await session.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
    if existing is not None:
        return {"status": "already_seeded"}

    hr_group = Group(name="Nhân sự", description="Phòng Nhân sự (Human Resources)")
    eng_group = Group(name="Kỹ thuật", description="Phòng Kỹ thuật (Engineering)")
    acc_group = Group(name="Kế toán", description="Phòng Kế toán (Accounting)")
    session.add_all([hr_group, eng_group, acc_group])
    await session.flush()

    admin_user = User(
        username="admin",
        display_name="Quản trị hệ thống",
        email="admin@company.local",
        password_hash=hash_password("AdminPass123!"),
        must_change_password=False,
        roles=["employee", "content_admin", "operator", "admin"],
        status=UserStatus.active,
        preferred_language=PreferredLanguage.vi,
    )
    operator_user = User(
        username="operator",
        display_name="Chuyên viên Vận hành (Ops)",
        email="ops@company.local",
        password_hash=hash_password("OperatorPass123!"),
        must_change_password=False,
        roles=["employee", "operator"],
        status=UserStatus.active,
        preferred_language=PreferredLanguage.vi,
    )
    emp_hr = User(
        username="emp_hr",
        display_name="Nhân viên Nhân sự",
        email="hr@company.local",
        password_hash=hash_password("EmployeePass123!"),
        must_change_password=False,
        roles=["employee"],
        status=UserStatus.active,
        preferred_language=PreferredLanguage.vi,
    )
    emp_eng = User(
        username="emp_eng",
        display_name="Kỹ sư Phần mềm",
        email="eng@company.local",
        password_hash=hash_password("EmployeePass123!"),
        must_change_password=False,
        roles=["employee"],
        status=UserStatus.active,
        preferred_language=PreferredLanguage.vi,
    )
    session.add_all([admin_user, operator_user, emp_hr, emp_eng])
    await session.flush()

    session.add_all(
        [
            UserGroup(user_id=admin_user.id, group_id=hr_group.id),
            UserGroup(user_id=admin_user.id, group_id=eng_group.id),
            UserGroup(user_id=emp_hr.id, group_id=hr_group.id),
            UserGroup(user_id=emp_eng.id, group_id=eng_group.id),
        ]
    )

    today = date.today()
    future_date = today + timedelta(days=60)
    past_expired = today - timedelta(days=10)

    docs_spec: list[dict[str, Any]] = [
        {
            "title": "Quy định nghỉ phép",
            "filename": "Quy_dinh_nghi_phep_v1.pdf",
            "mime_type": "application/pdf",
            "is_company_wide": True,
            "groups": [],
            "effective_from": today - timedelta(days=180),
            "expires_on": None,
            "language": DocumentLanguage.vi,
            "chunks": [
                {
                    "section_path": "Chương 2 > Điều 5: Số ngày phép năm",
                    "page": 4,
                    "content": (
                        "Điều 5 (Nhân viên chính thức): Người lao động ký hợp đồng chính thức và làm việc đủ "
                        "12 tháng tại công ty được nghỉ phép năm hưởng nguyên lương là 12 ngày mỗi năm. "
                        "Mỗi 5 năm thâm niên được cộng thêm 1 ngày phép. Nếu có thắc mắc về điều kiện nghỉ phép, "
                        "vui lòng liên hệ phòng Nhân sự qua số 0912345678."
                    ),
                },
                {
                    "section_path": "Chương 2 > Điều 6: Nghỉ phép nhân viên thử việc và nghỉ không lương",
                    "page": 5,
                    "content": (
                        "Điều 6 (Nhân viên thử việc & Nghỉ không lương): Trong thời gian thử việc (tối đa 2 tháng), "
                        "nhân viên thử việc chưa được tính phép năm riêng mà sẽ được cộng dồn sau khi ký hợp đồng "
                        "chính thức. Nhân viên chính thức có thể xin nghỉ không lương tối đa 15 ngày/năm khi được "
                        "trưởng bộ phận phê duyệt."
                    ),
                },
            ],
        },
        {
            "title": "Bảng lương 2026",
            "filename": "Bang_luong_2026.docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "is_company_wide": False,
            "groups": [hr_group.id],
            "effective_from": today - timedelta(days=30),
            "expires_on": None,
            "language": DocumentLanguage.vi,
            "chunks": [
                {
                    "section_path": "Mục 1 > Khung lương kỹ thuật 2026",
                    "page": 1,
                    "content": (
                        "Bảng lương nội bộ năm 2026 (Mật - chỉ lưu hành tại phòng Nhân sự): "
                        "Bậc 1: 18.000.000 VNĐ/tháng; Bậc 2: 26.000.000 VNĐ/tháng; "
                        "Bậc 3 (Senior): 38.000.000 VNĐ/tháng. Phụ cấp trách nhiệm bậc 3 là 4.000.000 VNĐ."
                    ),
                }
            ],
        },
        {
            "title": "Quy định công tác phí",
            "filename": "Chinh_sach_cong_tac_phi_2027.pdf",
            "mime_type": "application/pdf",
            "is_company_wide": True,
            "groups": [],
            "effective_from": future_date,
            "expires_on": None,
            "language": DocumentLanguage.vi,
            "chunks": [
                {
                    "section_path": "Điều 3 > Định mức công tác phí trong nước và nước ngoài",
                    "page": 2,
                    "content": (
                        "Định mức công tác phí: Công tác trong nước được hưởng phụ cấp lưu trú 500.000 VNĐ/ngày "
                        "và khách sạn tối đa 1.500.000 VNĐ/đêm. Công tác nước ngoài được hưởng phụ cấp 80 USD/ngày "
                        "tại khu vực Đông Nam Á và 120 USD/ngày tại các khu vực khác."
                    ),
                }
            ],
        },
        {
            "title": "Sổ tay nhân viên",
            "filename": "So_tay_nhan_vien.md",
            "mime_type": "text/markdown",
            "is_company_wide": True,
            "groups": [],
            "effective_from": today - timedelta(days=365),
            "expires_on": None,
            "language": DocumentLanguage.vi,
            "chunks": [
                {
                    "section_path": "Phần 1 > Giờ làm việc và làm việc từ xa",
                    "page": 1,
                    "content": (
                        "Giờ làm việc tiêu chuẩn của công ty là từ 8h30 đến 17h30 từ thứ Hai đến thứ Sáu "
                        "(nghỉ trưa từ 12h00 đến 13h00). Nhân viên được phép làm việc từ xa (remote) tối đa "
                        "2 ngày mỗi tháng khi đăng ký trước."
                    ),
                }
            ],
        },
        {
            "title": "Quy định hỗ trợ gửi xe 2024 (Cũ)",
            "filename": "Quy_dinh_gui_xe_2024.pdf",
            "mime_type": "application/pdf",
            "is_company_wide": True,
            "groups": [],
            "effective_from": today - timedelta(days=400),
            "expires_on": past_expired,
            "language": DocumentLanguage.vi,
            "chunks": [
                {
                    "section_path": "Điều 1 > Hỗ trợ phí gửi xe",
                    "page": 1,
                    "content": "Phụ cấp gửi xe năm 2024 là 150.000 VNĐ/tháng.",
                }
            ],
        },
    ]

    created_docs: dict[str, str] = {}
    for spec in docs_spec:
        doc = Document(
            title=spec["title"],
            is_company_wide=spec["is_company_wide"],
            effective_from=spec["effective_from"],
            expires_on=spec["expires_on"],
            status=DocumentStatus.active,
            created_by=admin_user.id,
        )
        session.add(doc)
        await session.flush()

        for gid in spec["groups"]:
            session.add(DocumentGroup(document_id=doc.id, group_id=gid))

        raw_bytes = "\n\n".join(c["content"] for c in spec["chunks"]).encode("utf-8")
        sha = hashlib.sha256(raw_bytes).hexdigest()
        ver = DocumentVersion(
            document_id=doc.id,
            version_number=1,
            original_filename=spec["filename"],
            mime_type=spec["mime_type"],
            size_bytes=len(raw_bytes),
            sha256=sha,
            blob_key=f"versions/{doc.id}/v1/{spec['filename']}",
            language=spec["language"],
            page_count=len(spec["chunks"]),
            status=DocumentVersionStatus.ready,
            token_count=sum(len(c["content"].split()) for c in spec["chunks"]),
            uploaded_by=admin_user.id,
            processed_at=utcnow(),
        )
        session.add(ver)
        await session.flush()
        doc.current_version_id = ver.id
        await store.put(ver.blob_key, raw_bytes, spec["mime_type"])

        for idx, c_spec in enumerate(spec["chunks"], start=1):
            masked_text, _ = mask_pii(c_spec["content"])
            contextual_text = f"{doc.title} — {c_spec['section_path']}: {masked_text}"
            vec = await emb.embed_query(contextual_text)
            chunk = Chunk(
                document_version_id=ver.id,
                document_id=doc.id,
                ordinal=idx,
                section_path=c_spec["section_path"],
                page_start=c_spec["page"],
                page_end=c_spec["page"],
                content=c_spec["content"],
                content_masked=masked_text,
                kind=ChunkKind.text,
                token_count=len(masked_text.split()),
                embedding=vec,
                tsv=f"{doc.title} {c_spec['section_path']} {masked_text}".lower(),
            )
            session.add(chunk)

        created_docs[doc.title] = str(doc.id)

    await session.commit()
    return {
        "status": "seeded",
        "users": ["admin", "emp_hr", "emp_eng"],
        "groups": ["Nhân sự", "Kỹ thuật", "Kế toán"],
        "documents": created_docs,
    }


async def _main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = get_session_factory()
    async with factory() as session:
        res = await seed_demo_data(session)
        print(res)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "seed-demo"
    if cmd == "seed-demo":
        asyncio.run(_main())
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
