"""0001: Foundational tables, HNSW vector index, GIN FTS index, trigram index (T012)."""

from __future__ import annotations

from alembic import op

from app.db.base import Base
from app.db.models import auth as _auth  # noqa: F401
from app.db.models import document as _doc  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    Base.metadata.create_all(
        bind=bind,
        tables=[
            Base.metadata.tables["users"],
            Base.metadata.tables["groups"],
            Base.metadata.tables["user_groups"],
            Base.metadata.tables["sessions"],
            Base.metadata.tables["documents"],
            Base.metadata.tables["document_groups"],
            Base.metadata.tables["document_versions"],
            Base.metadata.tables["chunks"],
        ],
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
            "ON chunks USING hnsw (embedding vector_cosine_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_documents_title_trgm "
            "ON documents USING gin (title gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_chunks_tsv_gin "
            "ON chunks USING gin (to_tsvector('simple', coalesce(section_path, '') || ' ' || content_masked))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    for name in [
        "chunks",
        "document_versions",
        "document_groups",
        "documents",
        "sessions",
        "user_groups",
        "groups",
        "users",
    ]:
        if name in Base.metadata.tables:
            Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
