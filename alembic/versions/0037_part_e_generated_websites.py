"""Part E: generated_websites metadata for auto-built static sites.

Revision ID: 0037_part_e_generated_websites
Revises: 0036_part_d_equity_portfolio
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_part_e_generated_websites"
down_revision: Union[str, Sequence[str], None] = "0036_part_d_equity_portfolio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generated_websites",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("template_type", sa.String(length=32), nullable=False, server_default="shop"),
        sa.Column("public_url", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("disk_path", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_generated_websites_org"),
        sa.UniqueConstraint("slug", name="uq_generated_websites_slug"),
    )
    op.create_index("ix_generated_websites_org", "generated_websites", ["organization_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_generated_websites_org", table_name="generated_websites")
    op.drop_table("generated_websites")
