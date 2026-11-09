"""0002: Conversations, turns, citations, and turn_traces tables (T027)."""

from __future__ import annotations

from alembic import op

from app.db.base import Base
from app.db.models import conversation as _conv  # noqa: F401

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[
            Base.metadata.tables["conversations"],
            Base.metadata.tables["turns"],
            Base.metadata.tables["citations"],
            Base.metadata.tables["turn_traces"],
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    for name in ["turn_traces", "citations", "turns", "conversations"]:
        if name in Base.metadata.tables:
            Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
