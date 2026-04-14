"""Append-only financial audit trail (immutable rows; application must never DELETE).

Revision ID: 0044_financial_audit_log
Revises: 0043_stock_price_alerts
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0044_financial_audit_log"
down_revision: Union[str, Sequence[str], None] = "0043_stock_price_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "financial_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column(
            "organization_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_financial_audit_logs_org_created",
        "financial_audit_logs",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_financial_audit_logs_user_created",
        "financial_audit_logs",
        ["user_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_financial_audit_logs_user_created", table_name="financial_audit_logs")
    op.drop_index("ix_financial_audit_logs_org_created", table_name="financial_audit_logs")
    op.drop_table("financial_audit_logs")
