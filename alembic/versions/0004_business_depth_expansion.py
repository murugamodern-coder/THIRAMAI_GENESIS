"""Phase 4 Business OS: department lead, staff profiles, attendance, opex, inventory unit cost.

Revision ID: 0004_business_depth_expansion
Revises: 0003_life_os_expansion
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_business_depth_expansion"
down_revision: Union[str, Sequence[str], None] = "0003_life_os_expansion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "departments",
        sa.Column("lead_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_departments_lead_user_id_users",
        "departments",
        "users",
        ["lead_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_departments_lead_user_id", "departments", ["lead_user_id"], unique=False)

    op.add_column(
        "inventory",
        sa.Column("unit_cost_pre_tax", sa.Numeric(18, 2), nullable=True),
    )

    op.create_table(
        "staff_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("basic_salary", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("joining_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
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
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_staff_profiles_user_org"),
    )
    op.create_index("ix_staff_profiles_organization_id", "staff_profiles", ["organization_id"], unique=False)
    op.create_index("ix_staff_profiles_user_id", "staff_profiles", ["user_id"], unique=False)
    op.create_index("ix_staff_profiles_department_id", "staff_profiles", ["department_id"], unique=False)

    op.create_table(
        "attendance_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("check_in", sa.DateTime(timezone=True), nullable=False),
        sa.Column("check_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="present"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["staff_id"], ["staff_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_logs_staff_id", "attendance_logs", ["staff_id"], unique=False)
    op.create_index("ix_attendance_logs_check_in", "attendance_logs", ["check_in"], unique=False)

    op.create_table(
        "operational_expenses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("amount_inr", sa.Numeric(18, 2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operational_expenses_org_date",
        "operational_expenses",
        ["organization_id", "expense_date"],
        unique=False,
    )


def downgrade() -> None:
    raise NotImplementedError("0004 downgrade not implemented.")
