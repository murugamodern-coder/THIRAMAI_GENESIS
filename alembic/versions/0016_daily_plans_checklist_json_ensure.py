"""Ensure ``daily_plans.checklist_json`` exists (idempotent safety migration).

Revision ID: 0016_daily_plans_checklist_json_ensure
Revises: 0015_daily_plans_checklist

Use when the DB revision row advanced without the column (failed migration, restore, etc.).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0016_daily_plans_checklist_json_ensure"
down_revision: Union[str, Sequence[str], None] = "0015_daily_plans_checklist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table("daily_plans"):
        return
    cols = {c["name"] for c in insp.get_columns("daily_plans")}
    if "checklist_json" in cols:
        return
    if bind.dialect.name == "postgresql":
        op.add_column(
            "daily_plans",
            sa.Column(
                "checklist_json",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    else:
        op.add_column(
            "daily_plans",
            sa.Column(
                "checklist_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    """Non-destructive: do not drop ``checklist_json`` (may pre-exist from 0015)."""
    pass
