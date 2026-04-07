"""Research vault: auto_generated status, resolved equity symbol, price snapshot.

Revision ID: 0019_research_vault_autonomy
Revises: 0018_research_business_category
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_research_vault_autonomy"
down_revision: Union[str, Sequence[str], None] = "0018_research_business_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "research_vault",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="auto_generated"),
    )
    op.add_column(
        "research_vault",
        sa.Column("resolved_symbol", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "research_vault",
        sa.Column("price_at_save", sa.Numeric(precision=18, scale=4), nullable=True),
    )
    op.add_column(
        "research_vault",
        sa.Column("quote_currency", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_vault", "quote_currency")
    op.drop_column("research_vault", "price_at_save")
    op.drop_column("research_vault", "resolved_symbol")
    op.drop_column("research_vault", "status")
