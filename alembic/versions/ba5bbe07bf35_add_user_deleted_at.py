"""add user deleted_at

Revision ID: ba5bbe07bf35
Revises: c76227522d4d
Create Date: 2026-10-09T12:10:47.250974

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ba5bbe07bf35"
down_revision: str | None = "c76227522d4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deleted_at")
