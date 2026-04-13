"""Phase 2 Jarvis: memory, proactive alerts, stock watchlist.

Revision ID: 0034_jarvis_memory_proactive_watchlist
Revises: 0033_business_os_phase2_inventory_po_liquidity
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_jarvis_memory_proactive_watchlist"
down_revision: Union[str, Sequence[str], None] = "0033_business_os_phase2_inventory_po_liquidity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind is not None and bind.dialect.name == "postgresql"
    payload_type = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()
    payload_default = sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")

    op.create_table(
        "jarvis_memory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("memory_key", sa.String(length=512), nullable=False),
        sa.Column("memory_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0.5"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "memory_key", name="uq_jarvis_memory_user_key"),
    )
    op.create_index(op.f("ix_jarvis_memory_user_id"), "jarvis_memory", ["user_id"], unique=False)

    json_type = postgresql.JSONB(astext_type=sa.Text()) if op.get_bind().dialect.name == "postgresql" else sa.JSON()

    op.create_table(
        "jarvis_proactive_alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("action_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", payload_type, nullable=False, server_default=payload_default),
        sa.Column("dedupe_key", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_jarvis_proactive_user_dedupe"),
    )
    op.create_index(
        op.f("ix_jarvis_proactive_alerts_user_id"), "jarvis_proactive_alerts", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_jarvis_proactive_alerts_organization_id"),
        "jarvis_proactive_alerts",
        ["organization_id"],
        unique=False,
    )

    op.create_table(
        "stock_watchlist_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange_suffix", sa.String(length=8), nullable=False, server_default="NS"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "symbol", name="uq_stock_watchlist_user_symbol"),
    )
    op.create_index(
        op.f("ix_stock_watchlist_entries_user_id"), "stock_watchlist_entries", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_watchlist_entries_user_id"), table_name="stock_watchlist_entries")
    op.drop_table("stock_watchlist_entries")
    op.drop_index(op.f("ix_jarvis_proactive_alerts_organization_id"), table_name="jarvis_proactive_alerts")
    op.drop_index(op.f("ix_jarvis_proactive_alerts_user_id"), table_name="jarvis_proactive_alerts")
    op.drop_table("jarvis_proactive_alerts")
    op.drop_index(op.f("ix_jarvis_memory_user_id"), table_name="jarvis_memory")
    op.drop_table("jarvis_memory")
