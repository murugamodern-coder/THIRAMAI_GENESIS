"""Executive OS: daily_plans agenda + research_vault.

Revision ID: 0010_executive_daily_plans_research_vault
Revises: 0009_ai_ltm_hitl
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_executive_daily_plans_research_vault"
down_revision: Union[str, Sequence[str], None] = "0009_ai_ltm_hitl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_plans",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("for_date", sa.Date(), nullable=False),
        sa.Column("plan_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "for_date", name="uq_daily_plans_user_for_date"),
    )
    op.create_index("ix_daily_plans_user_id", "daily_plans", ["user_id"], unique=False)

    op.create_table(
        "research_vault",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_vault_user_id", "research_vault", ["user_id"], unique=False)
    op.create_index("ix_research_vault_org_id", "research_vault", ["organization_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_research_vault_org_id", table_name="research_vault")
    op.drop_index("ix_research_vault_user_id", table_name="research_vault")
    op.drop_table("research_vault")
    op.drop_index("ix_daily_plans_user_id", table_name="daily_plans")
    op.drop_table("daily_plans")
