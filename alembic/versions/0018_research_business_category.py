"""Research vault: persist detected business category (template key).

Revision ID: 0018_research_business_category
Revises: 0017_executive_os_hub
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_research_business_category"
down_revision: Union[str, Sequence[str], None] = "0017_executive_os_hub"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "research_vault",
        sa.Column("business_category", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_vault", "business_category")
