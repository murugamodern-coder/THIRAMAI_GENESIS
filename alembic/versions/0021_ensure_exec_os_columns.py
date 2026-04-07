"""Idempotent: ensure Executive OS columns on ``daily_plans`` and ``research_vault``.

Revision ID: 0021_ensure_exec_os_columns
Revises: 0020_daily_plans_checklist_json

Repairs databases where ``alembic_version`` advanced without columns applied (failed migration,
restore from backup, etc.). Safe to run multiple times.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0021_ensure_exec_os_columns"
down_revision: Union[str, Sequence[str], None] = "0020_daily_plans_checklist_json"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    is_pg = bind.dialect.name == "postgresql"

    if insp.has_table("daily_plans"):
        cols = {c["name"] for c in insp.get_columns("daily_plans")}
        if "status" not in cols:
            op.add_column(
                "daily_plans",
                sa.Column(
                    "status",
                    sa.String(length=32),
                    nullable=False,
                    server_default="draft",
                ),
            )
        if "checklist_json" not in cols:
            if is_pg:
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

    if insp.has_table("research_vault"):
        rcols = {c["name"] for c in insp.get_columns("research_vault")}
        if "business_category" not in rcols:
            op.add_column(
                "research_vault",
                sa.Column("business_category", sa.String(length=32), nullable=True),
            )
        if "status" not in rcols:
            op.add_column(
                "research_vault",
                sa.Column(
                    "status",
                    sa.String(length=32),
                    nullable=False,
                    server_default="auto_generated",
                ),
            )
        if "resolved_symbol" not in rcols:
            op.add_column(
                "research_vault",
                sa.Column("resolved_symbol", sa.String(length=48), nullable=True),
            )
        if "price_at_save" not in rcols:
            op.add_column(
                "research_vault",
                sa.Column("price_at_save", sa.Numeric(precision=18, scale=4), nullable=True),
            )
        if "quote_currency" not in rcols:
            op.add_column(
                "research_vault",
                sa.Column("quote_currency", sa.String(length=8), nullable=True),
            )


def downgrade() -> None:
    """Non-destructive: columns may be required by the app."""
    pass
