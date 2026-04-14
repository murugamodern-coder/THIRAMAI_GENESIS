"""Learning loop for Jarvis proactive insights (acted / dismissed / ignored).

Revision ID: 0040_jarvis_proactive_feedback
Revises: 0039_jarvis_living_memory_engine
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_jarvis_proactive_feedback"
down_revision: Union[str, Sequence[str], None] = "0039_jarvis_living_memory_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jarvis_proactive_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_dedupe_key", sa.String(length=256), nullable=False),
        sa.Column("alert_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jarvis_proactive_feedback_user_created",
        "jarvis_proactive_feedback",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_jarvis_proactive_feedback_user_type_outcome",
        "jarvis_proactive_feedback",
        ["user_id", "alert_type", "outcome"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_jarvis_proactive_feedback_user_type_outcome", table_name="jarvis_proactive_feedback")
    op.drop_index("ix_jarvis_proactive_feedback_user_created", table_name="jarvis_proactive_feedback")
    op.drop_table("jarvis_proactive_feedback")
