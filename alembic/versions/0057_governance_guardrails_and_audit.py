"""Add governance guardrails and execution audit logs.

Revision ID: 0057_governance_guardrails_and_audit
Revises: 0056_learning_engine_tables
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057_governance_guardrails_and_audit"
down_revision: Union[str, Sequence[str], None] = "0056_learning_engine_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("guardrails"):
        op.create_table(
            "guardrails",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rule_name", sa.String(length=120), nullable=False),
            sa.Column("domain", sa.String(length=32), nullable=False),
            sa.Column("condition_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("action_limit_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_guardrails_user_id", "guardrails", ["user_id"], unique=False)
        op.create_index(
            "ix_guardrails_user_domain_enabled",
            "guardrails",
            ["user_id", "domain", "enabled"],
            unique=False,
        )

    if not insp.has_table("execution_audit_logs"):
        op.create_table(
            "execution_audit_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action_type", sa.String(length=64), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="success"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_execution_audit_logs_user_id", "execution_audit_logs", ["user_id"], unique=False)
        op.create_index(
            "ix_execution_audit_logs_user_created",
            "execution_audit_logs",
            ["user_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_execution_audit_logs_user_status",
            "execution_audit_logs",
            ["user_id", "status"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("execution_audit_logs"):
        op.drop_index("ix_execution_audit_logs_user_status", table_name="execution_audit_logs", if_exists=True)
        op.drop_index("ix_execution_audit_logs_user_created", table_name="execution_audit_logs", if_exists=True)
        op.drop_index("ix_execution_audit_logs_user_id", table_name="execution_audit_logs", if_exists=True)
        op.drop_table("execution_audit_logs")

    if insp.has_table("guardrails"):
        op.drop_index("ix_guardrails_user_domain_enabled", table_name="guardrails", if_exists=True)
        op.drop_index("ix_guardrails_user_id", table_name="guardrails", if_exists=True)
        op.drop_table("guardrails")
