"""Domain focus mode, knowledge, revenue ledger (domain P&L).

Revision ID: 0064_domain_dominion_mode
Revises: 0063_continuity_autonomous_engine
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0064_domain_dominion_mode"
down_revision: Union[str, Sequence[str], None] = "0063_continuity_autonomous_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("domain_dominion_profiles"):
        op.create_table(
            "domain_dominion_profiles",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column(
                "organization_id",
                sa.BigInteger(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("active_domain", sa.String(64), nullable=False, server_default="business"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("knowledge_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("meta_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("last_weekly_review_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_ddp_user", "domain_dominion_profiles", ["user_id"])
        op.create_index("ix_ddp_org", "domain_dominion_profiles", ["organization_id"])
        op.create_unique_constraint("uq_domain_dominion_user_org", "domain_dominion_profiles", ["user_id", "organization_id"])

    if not sa.inspect(bind).has_table("domain_revenue_ledger"):
        op.create_table(
            "domain_revenue_ledger",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column(
                "organization_id",
                sa.BigInteger(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("profile_id", sa.BigInteger(), sa.ForeignKey("domain_dominion_profiles.id", ondelete="SET NULL"), nullable=True),
            sa.Column("domain", sa.String(64), nullable=False, server_default=""),
            sa.Column("event_type", sa.String(24), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="INR"),
            sa.Column("ref_type", sa.String(32), nullable=True),
            sa.Column("ref_id", sa.BigInteger(), nullable=True, index=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("meta_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
        )
        op.create_index("ix_domain_revenue_user_created", "domain_revenue_ledger", ["user_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("domain_revenue_ledger"):
        op.drop_table("domain_revenue_ledger")
    if sa.inspect(bind).has_table("domain_dominion_profiles"):
        op.drop_table("domain_dominion_profiles")
