"""Phase 6 Factory OS v2: equipment registry, maintenance logs, work orders.

Revision ID: 0006_factory_v2_expansion
Revises: 0005_compliance_and_comms
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_factory_v2_expansion"
down_revision: Union[str, Sequence[str], None] = "0005_compliance_and_comms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "equipment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("project_stage_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("last_service_date", sa.Date(), nullable=True),
        sa.Column("next_service_due", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="Running"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_stage_id"], ["project_stages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equipment_organization_id", "equipment", ["organization_id"], unique=False)
    op.create_index("ix_equipment_project_stage_id", "equipment", ["project_stage_id"], unique=False)
    op.create_index("ix_equipment_next_service_due", "equipment", ["next_service_due"], unique=False)
    op.create_index("ix_equipment_status", "equipment", ["status"], unique=False)

    op.create_table(
        "maintenance_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("equipment_id", sa.BigInteger(), nullable=False),
        sa.Column("issue_description", sa.Text(), nullable=False),
        sa.Column("cost", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("fixed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("technician_name", sa.Text(), nullable=True),
        sa.Column("technician_staff_profile_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["technician_staff_profile_id"], ["staff_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_maintenance_logs_equipment_id", "maintenance_logs", ["equipment_id"], unique=False)
    op.create_index("ix_maintenance_logs_fixed_at", "maintenance_logs", ["fixed_at"], unique=False)

    op.create_table(
        "work_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_stage_id", sa.BigInteger(), nullable=False),
        sa.Column("equipment_id", sa.BigInteger(), nullable=True),
        sa.Column("assigned_staff_id", sa.BigInteger(), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assigned_staff_id"], ["staff_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_stage_id"], ["project_stages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_orders_project_stage_id", "work_orders", ["project_stage_id"], unique=False)
    op.create_index("ix_work_orders_equipment_id", "work_orders", ["equipment_id"], unique=False)
    op.create_index("ix_work_orders_assigned_staff_id", "work_orders", ["assigned_staff_id"], unique=False)
    op.create_index("ix_work_orders_status", "work_orders", ["status"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("0006 downgrade not implemented.")
