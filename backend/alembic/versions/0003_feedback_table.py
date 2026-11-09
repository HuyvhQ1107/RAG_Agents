"""0003: Feedback table (T057)."""

from __future__ import annotations

from alembic import op

from app.db.base import Base
from app.db.models import conversation as _conv  # noqa: F401

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["feedback"]],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "feedback" in Base.metadata.tables:
        Base.metadata.tables["feedback"].drop(bind=bind, checkfirst=True)
