"""Add security_audit_logs (Week 1 Day 2).

Revision ID: 0071_security_audit_logs
Revises: 0070_add_performance_indexes
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0071_security_audit_logs"
down_revision: Union[str, Sequence[str], None] = "0070_add_performance_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower() if bind is not None else "postgresql"
    is_pg = dialect == "postgresql"
    details_type = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()
    details_default = sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")

    op.create_table(
        "security_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("details", details_type, nullable=False, server_default=details_default),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_audit_logs_event_type", "security_audit_logs", ["event_type"], unique=False)
    op.create_index("ix_security_audit_logs_user_id", "security_audit_logs", ["user_id"], unique=False)
    op.create_index("ix_security_audit_logs_created_at", "security_audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_security_audit_logs_created_at", table_name="security_audit_logs")
    op.drop_index("ix_security_audit_logs_user_id", table_name="security_audit_logs")
    op.drop_index("ix_security_audit_logs_event_type", table_name="security_audit_logs")
    op.drop_table("security_audit_logs")
