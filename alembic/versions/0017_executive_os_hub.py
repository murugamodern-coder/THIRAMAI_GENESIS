"""Executive OS hub: planner snapshots, vault uploads, mission progress.

Revision ID: 0017_executive_os_hub
Revises: 0016_daily_plans_checklist_json_ensure
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_executive_os_hub"
down_revision: Union[str, Sequence[str], None] = "0016_daily_plans_checklist_json_ensure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        checklist_col = sa.Column(
            "checklist_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        )
    else:
        checklist_col = sa.Column(
            "checklist_json",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        )
    op.create_table(
        "daily_plan_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("for_date", sa.Date(), nullable=False),
        sa.Column("plan_text", sa.Text(), nullable=False, server_default=""),
        checklist_col,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_plan_snapshots_user_created", "daily_plan_snapshots", ["user_id", "created_at"])

    op.create_table(
        "executive_vault_documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_executive_vault_documents_user_id", "executive_vault_documents", ["user_id"])
    op.create_index(
        "ix_executive_vault_documents_org_user",
        "executive_vault_documents",
        ["organization_id", "user_id"],
    )

    op.add_column(
        "personal_missions",
        sa.Column("progress_percent", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("personal_missions", "progress_percent")
    op.drop_index("ix_executive_vault_documents_org_user", table_name="executive_vault_documents")
    op.drop_index("ix_executive_vault_documents_user_id", table_name="executive_vault_documents")
    op.drop_table("executive_vault_documents")
    op.drop_index("ix_daily_plan_snapshots_user_created", table_name="daily_plan_snapshots")
    op.drop_table("daily_plan_snapshots")
