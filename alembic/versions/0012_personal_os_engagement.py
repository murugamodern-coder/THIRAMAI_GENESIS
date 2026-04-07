"""Personal OS: engagement streak, suggestion feedback, mission updated_at.

Revision ID: 0012_personal_os_engagement
Revises: 0011_ledger_transactions
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_personal_os_engagement"
down_revision: Union[str, Sequence[str], None] = "0011_ledger_transactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personal_missions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )

    op.create_table(
        "personal_engagement",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("last_active_date", sa.Date(), nullable=True),
        sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index("ix_personal_engagement_last_active_date", "personal_engagement", ["last_active_date"])

    op.create_table(
        "personal_suggestion_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("suggestion_text", sa.Text(), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_suggestion_feedback_user_id", "personal_suggestion_feedback", ["user_id"])
    op.create_index(
        "ix_personal_suggestion_feedback_organization_id", "personal_suggestion_feedback", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_personal_suggestion_feedback_organization_id", table_name="personal_suggestion_feedback")
    op.drop_index("ix_personal_suggestion_feedback_user_id", table_name="personal_suggestion_feedback")
    op.drop_table("personal_suggestion_feedback")
    op.drop_index("ix_personal_engagement_last_active_date", table_name="personal_engagement")
    op.drop_table("personal_engagement")
    op.drop_column("personal_missions", "updated_at")
