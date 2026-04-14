"""User product profile JSON (onboarding, demo, wow) for growth + UX state.

Revision ID: 0045_user_product_profile
Revises: 0044_financial_audit_log
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_user_product_profile"
down_revision: Union[str, Sequence[str], None] = "0044_financial_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("product_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "product_profile")
