"""usage_logs — product analytics and event stream (Phase 8).

Revision ID: 0022_usage_logs
Revises: 0021_ensure_exec_os_columns
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_usage_logs"
down_revision: Union[str, Sequence[str], None] = "0021_ensure_exec_os_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    json_t = postgresql.JSONB() if is_pg else sa.JSON()

    op.create_table(
        "usage_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("org_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("metadata", json_t, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_logs_org_created", "usage_logs", ["org_id", "created_at"])
    op.create_index("ix_usage_logs_org_action", "usage_logs", ["org_id", "action"])
    op.create_index(op.f("ix_usage_logs_user_id"), "usage_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_logs_user_id"), table_name="usage_logs")
    op.drop_index("ix_usage_logs_org_id_action", table_name="usage_logs")
    op.drop_index("ix_usage_logs_org_created", table_name="usage_logs")
    op.drop_table("usage_logs")
