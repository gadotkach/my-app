"""add api_request_logs

Revision ID: b54d049e4286
Revises: head
Create Date: 2026-10-09T10:29:18.150821

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b54d049e4286"
down_revision: str | None = "ad3c2bb462b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_request_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("marketplace", sa.String(length=50), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_request_logs_user_id", "api_request_logs", ["user_id"])
    op.create_index("ix_api_request_logs_marketplace", "api_request_logs", ["marketplace"])
    op.create_index("ix_api_request_logs_endpoint", "api_request_logs", ["endpoint"])
    op.create_index("ix_api_request_logs_status_code", "api_request_logs", ["status_code"])
    op.create_index("ix_api_request_logs_created_at", "api_request_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_api_request_logs_created_at", table_name="api_request_logs")
    op.drop_index("ix_api_request_logs_status_code", table_name="api_request_logs")
    op.drop_index("ix_api_request_logs_endpoint", table_name="api_request_logs")
    op.drop_index("ix_api_request_logs_marketplace", table_name="api_request_logs")
    op.drop_index("ix_api_request_logs_user_id", table_name="api_request_logs")
    op.drop_table("api_request_logs")
