"""Control plane: audit_logs + alerts + jobs (enterprise backend layer).

Revision ID: 0023_control_plane_audit_alerts_jobs
Revises: 0022_usage_logs
Create Date: 2026-04-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_control_plane_audit_alerts_jobs"
down_revision = "0022_usage_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("action_type", sa.String(length=128), nullable=False, index=True),
        sa.Column("entity", sa.String(length=128), nullable=False, index=True),
        sa.Column("entity_id", sa.String(length=128), nullable=True, index=True),
        sa.Column("source", sa.String(length=16), nullable=False, index=True),  # AI|USER
        sa.Column("result", sa.String(length=16), nullable=False, index=True),  # SUCCESS|FAIL
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )
    op.create_index("ix_audit_logs_org_created", "audit_logs", ["org_id", "created_at"])

    op.create_table(
        "control_plane_alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.String(length=64), nullable=False, index=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, index=True),  # info|warning|error|critical
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cp_alerts_org_created", "control_plane_alerts", ["org_id", "created_at"])

    op.create_table(
        "control_plane_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.BigInteger(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.String(length=64), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, index=True),  # scheduled|running|succeeded|failed|cancelled
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_cp_jobs_org_scheduled", "control_plane_jobs", ["org_id", "scheduled_at"])


def downgrade() -> None:
    op.drop_index("ix_cp_jobs_org_scheduled", table_name="control_plane_jobs")
    op.drop_table("control_plane_jobs")
    op.drop_index("ix_cp_alerts_org_created", table_name="control_plane_alerts")
    op.drop_table("control_plane_alerts")
    op.drop_index("ix_audit_logs_org_created", table_name="audit_logs")
    op.drop_table("audit_logs")

