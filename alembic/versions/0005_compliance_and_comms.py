"""Phase 5: compliance cases + comms inbox (Email/SMS/System).

Revision ID: 0005_compliance_and_comms
Revises: 0004_business_depth_expansion
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_compliance_and_comms"
down_revision: Union[str, Sequence[str], None] = "0004_business_depth_expansion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_cases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="normal"),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "external_ref", name="uq_compliance_cases_org_external_ref"),
    )
    op.create_index("ix_compliance_cases_organization_id", "compliance_cases", ["organization_id"], unique=False)
    op.create_index("ix_compliance_cases_deadline", "compliance_cases", ["deadline"], unique=False)
    op.create_index("ix_compliance_cases_category", "compliance_cases", ["category"], unique=False)

    op.create_table(
        "comms_inbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_summary", sa.Text(), nullable=False),
        sa.Column("intelligence_tier", sa.String(length=32), nullable=True),
        sa.Column("related_case_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_case_id"], ["compliance_cases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comms_inbox_organization_id", "comms_inbox", ["organization_id"], unique=False)
    op.create_index("ix_comms_inbox_related_case_id", "comms_inbox", ["related_case_id"], unique=False)
    op.create_index("ix_comms_inbox_intelligence_tier", "comms_inbox", ["intelligence_tier"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("0005 downgrade not implemented.")
