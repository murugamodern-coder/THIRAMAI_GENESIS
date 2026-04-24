"""Add integration connections and outgoing message logs.

Revision ID: 0054_integrations_and_message_logs
Revises: 0053_automation_rules_and_logs
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054_integrations_and_message_logs"
down_revision: Union[str, Sequence[str], None] = "0053_automation_rules_and_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("integrations"):
        op.create_table(
            "integrations",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_integrations_user_id", "integrations", ["user_id"], unique=False)
        op.create_index("ix_integrations_user_type", "integrations", ["user_id", "type"], unique=False)

    if not insp.has_table("integration_message_logs"):
        op.create_table(
            "integration_message_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("integration_id", sa.BigInteger(), sa.ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("recipient", sa.String(length=300), nullable=False),
            sa.Column("subject", sa.String(length=300), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="success"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_integration_message_logs_user_id", "integration_message_logs", ["user_id"], unique=False)
        op.create_index(
            "ix_integration_message_logs_user_created",
            "integration_message_logs",
            ["user_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_integration_message_logs_integration",
            "integration_message_logs",
            ["integration_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("integration_message_logs"):
        op.drop_index("ix_integration_message_logs_integration", table_name="integration_message_logs", if_exists=True)
        op.drop_index("ix_integration_message_logs_user_created", table_name="integration_message_logs", if_exists=True)
        op.drop_index("ix_integration_message_logs_user_id", table_name="integration_message_logs", if_exists=True)
        op.drop_table("integration_message_logs")

    if insp.has_table("integrations"):
        op.drop_index("ix_integrations_user_type", table_name="integrations", if_exists=True)
        op.drop_index("ix_integrations_user_id", table_name="integrations", if_exists=True)
        op.drop_table("integrations")
