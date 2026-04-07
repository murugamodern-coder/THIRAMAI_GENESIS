"""Add ``daily_plans.checklist_json`` (JSONB) when missing for checklist feature.

Revision ID: 0020_daily_plans_checklist_json
Revises: 0019_research_vault_autonomy

Idempotent: safe if the column already exists (e.g. applied 0015/0016 earlier).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0020_daily_plans_checklist_json"
down_revision: Union[str, Sequence[str], None] = "0019_research_vault_autonomy"
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
    """Non-destructive: column may be required by app; do not drop."""
    pass
