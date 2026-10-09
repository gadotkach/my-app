"""add last_activity_at to users

Revision ID: 55f68c47be59
Revises: b54d049e4286
Create Date: 2026-10-09 11:29:05.342962

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55f68c47be59'
down_revision: Union[str, None] = 'b54d049e4286'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_last_activity_at", "users", ["last_activity_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_users_last_activity_at", table_name="users")
    op.drop_column("users", "last_activity_at")
