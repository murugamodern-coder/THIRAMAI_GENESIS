"""Daily agenda checklist + reminder metadata (JSON on ``daily_plans``).

Revision ID: 0015_daily_plans_checklist
Revises: 0014_research_corrections
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_daily_plans_checklist"
down_revision: Union[str, Sequence[str], None] = "0014_research_corrections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
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
    op.drop_column("daily_plans", "checklist_json")
