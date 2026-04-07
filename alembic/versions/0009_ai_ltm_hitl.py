"""AI long-term memory support tables: HITL feedback + rule weights.

Revision ID: 0009_ai_ltm_hitl
Revises: 0008_jwt_refresh_tokens
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_ai_ltm_hitl"
down_revision: Union[str, Sequence[str], None] = "0008_jwt_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_hitl_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_key", sa.String(length=128), nullable=False),
        sa.Column("sentiment", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
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
    op.create_index("ix_ai_hitl_feedback_org", "ai_hitl_feedback", ["organization_id"], unique=False)

    op.create_table(
        "ai_rule_weights",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_key", sa.String(length=128), nullable=False),
        sa.Column("weight", sa.Numeric(6, 3), server_default="1.000", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "rule_key"),
    )


def downgrade() -> None:
    raise NotImplementedError("0009 downgrade not implemented.")
