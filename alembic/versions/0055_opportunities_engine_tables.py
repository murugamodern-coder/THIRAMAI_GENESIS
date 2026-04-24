"""Add opportunities and profit logs tables.

Revision ID: 0055_opportunities_engine_tables
Revises: 0054_integrations_and_message_logs
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0055_opportunities_engine_tables"
down_revision: Union[str, Sequence[str], None] = "0054_integrations_and_message_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("opportunities"):
        op.create_table(
            "opportunities",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("expected_profit", sa.Float(), nullable=False, server_default="0"),
            sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status in ('new','approved','executed','rejected')", name="ck_opportunities_status"),
        )
        op.create_index("ix_opportunities_user_id", "opportunities", ["user_id"], unique=False)
        op.create_index(
            "ix_opportunities_user_status_created",
            "opportunities",
            ["user_id", "status", "created_at"],
            unique=False,
        )

    if not insp.has_table("opportunity_profit_logs"):
        op.create_table(
            "opportunity_profit_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("opportunity_id", sa.BigInteger(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
            sa.Column("profit_loss_amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("note", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_opportunity_profit_logs_opportunity_id", "opportunity_profit_logs", ["opportunity_id"], unique=False)
        op.create_index(
            "ix_opp_profit_logs_opp_created",
            "opportunity_profit_logs",
            ["opportunity_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("opportunity_profit_logs"):
        op.drop_index("ix_opp_profit_logs_opp_created", table_name="opportunity_profit_logs", if_exists=True)
        op.drop_index("ix_opportunity_profit_logs_opportunity_id", table_name="opportunity_profit_logs", if_exists=True)
        op.drop_table("opportunity_profit_logs")

    if insp.has_table("opportunities"):
        op.drop_index("ix_opportunities_user_status_created", table_name="opportunities", if_exists=True)
        op.drop_index("ix_opportunities_user_id", table_name="opportunities", if_exists=True)
        op.drop_table("opportunities")
