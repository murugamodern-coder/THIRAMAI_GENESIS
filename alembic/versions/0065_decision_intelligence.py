"""Decision intelligence sessions: multi-option decisions + outcomes for learning.

Revision ID: 0065_decision_intelligence
Revises: 0064_domain_dominion_mode
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0065_decision_intelligence"
down_revision: Union[str, Sequence[str], None] = "0064_domain_dominion_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("decision_intelligence_sessions"):
        op.create_table(
            "decision_intelligence_sessions",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column(
                "organization_id",
                sa.BigInteger(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("title", sa.String(300), nullable=False, server_default=""),
            sa.Column("decision_brief", sa.Text(), nullable=False, server_default=""),
            sa.Column("context_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("options_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("recommendation_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
            sa.Column("selected_option", sa.String(2), nullable=True),
            sa.Column("result_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "status in ('draft','selected','closed')", name="ck_decision_intel_status"
            ),
        )
        op.create_index("ix_decision_intel_user_created", "decision_intelligence_sessions", ["user_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("decision_intelligence_sessions"):
        op.drop_table("decision_intelligence_sessions")
