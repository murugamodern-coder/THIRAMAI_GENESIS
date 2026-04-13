"""Agro subsidy cases, per-org business tasks, production log extensions.

Revision ID: 0032_business_os_subsidy_tasks
Revises: 0031_push_subscriptions
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_business_os_subsidy_tasks"
down_revision: Union[str, Sequence[str], None] = "0031_push_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind is not None and bind.dialect.name == "postgresql"
    checklist_type = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()
    checklist_default = sa.text("'[]'::jsonb") if is_pg else sa.text("'[]'")

    op.create_table(
        "agro_subsidy_cases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("farmer_name", sa.Text(), nullable=False),
        sa.Column("village", sa.Text(), nullable=False, server_default=""),
        sa.Column("survey_number", sa.Text(), nullable=False, server_default=""),
        sa.Column("scheme_name", sa.Text(), nullable=False),
        sa.Column("application_status", sa.String(64), nullable=False, server_default="draft"),
        sa.Column("subsidy_pending_inr", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("subsidy_received_inr", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agro_subsidy_cases_org", "agro_subsidy_cases", ["organization_id"])

    op.create_table(
        "business_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("owner_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("task_type", sa.String(64), nullable=False, server_default="general"),
        sa.Column("checklist_json", checklist_type, nullable=False, server_default=checklist_default),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_tasks_org", "business_tasks", ["organization_id"])
    op.create_index("ix_business_tasks_org_status", "business_tasks", ["organization_id", "status"])

    op.add_column("production_logs", sa.Column("machine_hours", sa.Numeric(18, 2), nullable=True))
    op.add_column("production_logs", sa.Column("quality_status", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_business_tasks_org_status", table_name="business_tasks")
    op.drop_index("ix_business_tasks_org", table_name="business_tasks")
    op.drop_table("business_tasks")
    op.drop_index("ix_agro_subsidy_cases_org", table_name="agro_subsidy_cases")
    op.drop_table("agro_subsidy_cases")
    op.drop_column("production_logs", "quality_status")
    op.drop_column("production_logs", "machine_hours")
