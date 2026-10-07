"""add last_sync_at to marketplace_accounts (manual)

Revision ID: manual_last_sync_at
Revises: 0f411e6cc3ad
Create Date: 2026-10-06 17:35:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'manual_last_sync_at'
down_revision: Union[str, None] = '0f411e6cc3ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'marketplace_accounts' AND column_name = 'last_sync_at'
    """))
    if result.fetchone() is None:
        op.add_column(
            'marketplace_accounts',
            sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True)
        )
        print("OK: Column last_sync_at added")
    else:
        print("SKIP: Column already exists")


def downgrade() -> None:
    op.drop_column('marketplace_accounts', 'last_sync_at')
