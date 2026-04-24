"""Add persistent research projects table.

Revision ID: 0061_research_projects_table
Revises: 0060_money_loop_optimizer_toggle
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0061_research_projects_table"
down_revision: Union[str, Sequence[str], None] = "0060_money_loop_optimizer_toggle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table_name: str, column_name: str) -> bool:
    try:
        cols = insp.get_columns(table_name)
    except Exception:
        return False
    return any(str(c.get("name")) == column_name for c in cols)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("research_projects"):
        op.create_table(
            "research_projects",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("domain", sa.String(length=64), nullable=False, server_default="general"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("folders_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("sources_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("notes_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("summaries_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("experiments_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("outputs_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_research_projects_user_id", "research_projects", ["user_id"], unique=False)
        op.create_index("ix_research_projects_org_id", "research_projects", ["organization_id"], unique=False)
        op.create_index("ix_research_projects_user_created", "research_projects", ["user_id", "created_at"], unique=False)
        op.create_index("ix_research_projects_user_status", "research_projects", ["user_id", "status"], unique=False)
        return

    # Idempotent additive behavior for existing environments.
    for name, col in (
        ("folders_json", sa.Column("folders_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        ("sources_json", sa.Column("sources_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        ("notes_json", sa.Column("notes_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        ("summaries_json", sa.Column("summaries_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        ("experiments_json", sa.Column("experiments_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        ("outputs_json", sa.Column("outputs_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
        ("last_error", sa.Column("last_error", sa.Text(), nullable=True)),
    ):
        if not _has_column(insp, "research_projects", name):
            op.add_column("research_projects", col)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("research_projects"):
        return
    op.drop_index("ix_research_projects_user_status", table_name="research_projects", if_exists=True)
    op.drop_index("ix_research_projects_user_created", table_name="research_projects", if_exists=True)
    op.drop_index("ix_research_projects_org_id", table_name="research_projects", if_exists=True)
    op.drop_index("ix_research_projects_user_id", table_name="research_projects", if_exists=True)
    op.drop_table("research_projects")
