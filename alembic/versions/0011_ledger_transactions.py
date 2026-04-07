"""ERP ledger journal: ledger_transactions (maps architecture ``transactions``).

Revision ID: 0011_ledger_transactions
Revises: 0010_executive_daily_plans_research_vault
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_ledger_transactions"
down_revision: Union[str, Sequence[str], None] = "0010_executive_daily_plans_research_vault"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ledger_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("entry_type", sa.String(length=32), nullable=False, server_default="adjustment"),
        sa.Column("amount_inr", sa.Numeric(18, 2), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("reference", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ledger_transactions_organization_id", "ledger_transactions", ["organization_id"])
    op.create_index("ix_ledger_transactions_user_id", "ledger_transactions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ledger_transactions_user_id", table_name="ledger_transactions")
    op.drop_index("ix_ledger_transactions_organization_id", table_name="ledger_transactions")
    op.drop_table("ledger_transactions")
