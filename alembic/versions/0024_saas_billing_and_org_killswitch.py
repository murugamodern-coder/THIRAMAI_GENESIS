"""SaaS layer: org kill switch + plans/subscriptions/usage_metrics.

Revision ID: 0024_saas_billing_and_org_killswitch
Revises: 0023_control_plane_audit_alerts_jobs
Create Date: 2026-04-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024_saas_billing_and_org_killswitch"
down_revision = "0023_control_plane_audit_alerts_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_organizations_is_disabled", "organizations", ["is_disabled"])

    op.create_table(
        "saas_plans",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "saas_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("plan_id", sa.BigInteger(), sa.ForeignKey("saas_plans.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("status", sa.String(length=32), nullable=False, index=True),  # active|trialing|past_due|cancelled
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_saas_subscriptions_org_status", "saas_subscriptions", ["org_id", "status"])

    op.create_table(
        "saas_usage_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("metric", sa.String(length=64), nullable=False, index=True),  # api_calls|ai_actions|active_users|dashboard_refresh
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("value", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_saas_usage_org_metric_window", "saas_usage_metrics", ["org_id", "metric", "window_start"])


def downgrade() -> None:
    op.drop_index("ix_saas_usage_org_metric_window", table_name="saas_usage_metrics")
    op.drop_table("saas_usage_metrics")
    op.drop_index("ix_saas_subscriptions_org_status", table_name="saas_subscriptions")
    op.drop_table("saas_subscriptions")
    op.drop_table("saas_plans")
    op.drop_index("ix_organizations_is_disabled", table_name="organizations")
    op.drop_column("organizations", "is_disabled")

