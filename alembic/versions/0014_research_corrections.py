"""Research Hub feedback loop: ``research_corrections`` for Command Bar notes.

Revision ID: 0014_research_corrections
Revises: 0013_users_username
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_research_corrections"
down_revision: Union[str, Sequence[str], None] = "0013_users_username"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_corrections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'command_bar'"),
        ),
        sa.Column("related_research_vault_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["related_research_vault_id"],
            ["research_vault.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_corrections_user_id", "research_corrections", ["user_id"])
    op.create_index(
        "ix_research_corrections_org_user_created",
        "research_corrections",
        ["organization_id", "user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_corrections_org_user_created", table_name="research_corrections")
    op.drop_index("ix_research_corrections_user_id", table_name="research_corrections")
    op.drop_table("research_corrections")
