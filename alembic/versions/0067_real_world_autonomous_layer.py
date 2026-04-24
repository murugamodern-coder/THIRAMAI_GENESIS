"""Real-world execution tracking + negotiation deals (memory + status).

Revision ID: 0067_real_world_autonomous_layer
Revises: 0066_strategy_experiments_table
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0067_real_world_autonomous_layer"
down_revision: Union[str, Sequence[str], None] = "0066_strategy_experiments_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("real_world_executions"):
        op.create_table(
            "real_world_executions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("public_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "organization_id",
                sa.BigInteger(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action_type", sa.String(64), nullable=False, server_default="general"),
            sa.Column("label", sa.String(500), nullable=False, server_default=""),
            sa.Column("state", sa.String(24), nullable=False, server_default="initiated"),
            sa.Column("expected_outcome_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("actual_outcome_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("api_succeeded", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("outcome_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("outcome_assessment", sa.String(24), nullable=True),
            sa.Column("verification_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("meta_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "state in ('initiated','in_progress','completed','failed')",
                name="ck_rwe_state",
            ),
        )
        op.create_index("ix_rwe_public_id", "real_world_executions", ["public_id"], unique=True)
        op.create_index("ix_rwe_user_state_created", "real_world_executions", ["user_id", "state", "created_at"])
    if not insp.has_table("negotiation_deals"):
        op.create_table(
            "negotiation_deals",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("public_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "organization_id",
                sa.BigInteger(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="open"),
            sa.Column("context_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("messages_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("last_analysis_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "status in ('open','negotiating','closed','lost')",
                name="ck_negdeal_status",
            ),
        )
        op.create_index("ix_negdeals_public_id", "negotiation_deals", ["public_id"], unique=True)
        op.create_index("ix_negdeals_user_status", "negotiation_deals", ["user_id", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("negotiation_deals"):
        op.drop_table("negotiation_deals")
    if sa.inspect(bind).has_table("real_world_executions"):
        op.drop_table("real_world_executions")
