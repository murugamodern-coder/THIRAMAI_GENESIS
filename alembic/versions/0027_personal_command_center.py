"""Personal Command Center: personal finance, vitals, medicine, doctor visits, research, budgets.

Revision ID: 0027_personal_command_center
Revises: 0026_users_schema_repair
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_personal_command_center"
down_revision: Union[str, Sequence[str], None] = "0026_users_schema_repair"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personal_missions",
        sa.Column("priority", sa.String(length=8), nullable=False, server_default="P2"),
    )
    op.create_index("ix_personal_missions_priority", "personal_missions", ["priority"])

    op.create_table(
        "personal_expenses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("subcategory", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("spent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("notes_cipher", sa.LargeBinary(), nullable=True),
        sa.Column("notes_encrypted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_expenses_user_id", "personal_expenses", ["user_id"])
    op.create_index("ix_personal_expenses_spent_at", "personal_expenses", ["spent_at"])
    op.create_index("ix_personal_expenses_category", "personal_expenses", ["category"])

    op.create_table(
        "personal_loans",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("loan_kind", sa.String(length=32), nullable=False),
        sa.Column("lender", sa.Text(), nullable=True),
        sa.Column("principal_outstanding", sa.Numeric(16, 2), nullable=True),
        sa.Column("emi_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("interest_rate_apr", sa.Numeric(6, 3), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes_cipher", sa.LargeBinary(), nullable=True),
        sa.Column("notes_encrypted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_loans_user_id", "personal_loans", ["user_id"])
    op.create_index("ix_personal_loans_next_due", "personal_loans", ["next_due_date"])
    op.create_index("ix_personal_loans_kind", "personal_loans", ["loan_kind"])

    op.create_table(
        "vital_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 2), nullable=True),
        sa.Column("bp_systolic", sa.Integer(), nullable=True),
        sa.Column("bp_diastolic", sa.Integer(), nullable=True),
        sa.Column("blood_glucose_mg_dl", sa.Numeric(8, 2), nullable=True),
        sa.Column("sleep_hours", sa.Numeric(5, 2), nullable=True),
        sa.Column("stress_1_10", sa.SmallInteger(), nullable=True),
        sa.Column("water_glasses", sa.Integer(), nullable=True),
        sa.Column("notes_cipher", sa.LargeBinary(), nullable=True),
        sa.Column("notes_encrypted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vital_records_user_id", "vital_records", ["user_id"])
    op.create_index("ix_vital_records_recorded_at", "vital_records", ["recorded_at"])

    op.create_table(
        "medicine_trackers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("dosage_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "schedule_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes_cipher", sa.LargeBinary(), nullable=True),
        sa.Column("notes_encrypted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_medicine_trackers_user_id", "medicine_trackers", ["user_id"])
    op.create_index("ix_medicine_trackers_active", "medicine_trackers", ["is_active"])

    op.create_table(
        "doctor_visits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("visited_on", sa.Date(), nullable=False),
        sa.Column("doctor_name", sa.Text(), nullable=False),
        sa.Column("specialty", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("diagnosis_cipher", sa.LargeBinary(), nullable=True),
        sa.Column("prescription_cipher", sa.LargeBinary(), nullable=True),
        sa.Column("diagnosis_encrypted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_doctor_visits_user_id", "doctor_visits", ["user_id"])
    op.create_index("ix_doctor_visits_visited_on", "doctor_visits", ["visited_on"])

    op.create_table(
        "research_projects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "links_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_projects_user_id", "research_projects", ["user_id"])
    op.create_index("ix_research_projects_status", "research_projects", ["status"])

    op.create_table(
        "personal_budgets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("subcategory", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("budget_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("overspend_alert_pct", sa.SmallInteger(), nullable=False, server_default="15"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_budgets_user_period", "personal_budgets", ["user_id", "period_start", "period_end"])


def downgrade() -> None:
    op.drop_index("ix_personal_budgets_user_period", table_name="personal_budgets")
    op.drop_table("personal_budgets")
    op.drop_index("ix_research_projects_status", table_name="research_projects")
    op.drop_index("ix_research_projects_user_id", table_name="research_projects")
    op.drop_table("research_projects")
    op.drop_index("ix_doctor_visits_visited_on", table_name="doctor_visits")
    op.drop_index("ix_doctor_visits_user_id", table_name="doctor_visits")
    op.drop_table("doctor_visits")
    op.drop_index("ix_medicine_trackers_active", table_name="medicine_trackers")
    op.drop_index("ix_medicine_trackers_user_id", table_name="medicine_trackers")
    op.drop_table("medicine_trackers")
    op.drop_index("ix_vital_records_recorded_at", table_name="vital_records")
    op.drop_index("ix_vital_records_user_id", table_name="vital_records")
    op.drop_table("vital_records")
    op.drop_index("ix_personal_loans_kind", table_name="personal_loans")
    op.drop_index("ix_personal_loans_next_due", table_name="personal_loans")
    op.drop_index("ix_personal_loans_user_id", table_name="personal_loans")
    op.drop_table("personal_loans")
    op.drop_index("ix_personal_expenses_category", table_name="personal_expenses")
    op.drop_index("ix_personal_expenses_spent_at", table_name="personal_expenses")
    op.drop_index("ix_personal_expenses_user_id", table_name="personal_expenses")
    op.drop_table("personal_expenses")
    op.drop_index("ix_personal_missions_priority", table_name="personal_missions")
    op.drop_column("personal_missions", "priority")
