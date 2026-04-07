"""Autonomy layer: per-org auto mode + policy + feedback.

Revision ID: 0025_autonomy_settings_and_feedback
Revises: 0024_saas_billing_and_org_killswitch
Create Date: 2026-04-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0025_autonomy_settings_and_feedback"
down_revision = "0024_saas_billing_and_org_killswitch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autonomy_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("auto_mode_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "autonomy_feedback",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        # decision_id references ai_decisions in code, but we avoid a hard FK so this migration is
        # compatible with deployments that haven't enabled Phase-3 decision persistence yet.
        sa.Column("decision_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("action_type", sa.String(length=128), nullable=False, index=True),
        sa.Column("outcome", sa.String(length=32), nullable=False, index=True),  # succeeded|failed|overridden
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )
    op.create_index("ix_autonomy_feedback_org_created", "autonomy_feedback", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_autonomy_feedback_org_created", table_name="autonomy_feedback")
    op.drop_table("autonomy_feedback")
    op.drop_table("autonomy_settings")

