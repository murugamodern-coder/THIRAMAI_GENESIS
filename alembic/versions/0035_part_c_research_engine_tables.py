"""Part C: research_documents + govt_schemes for market intelligence pipeline.

Revision ID: 0035_part_c_research_engine
Revises: 0034_jarvis_memory_proactive_watchlist
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_part_c_research_engine"
down_revision: Union[str, Sequence[str], None] = "0034_jarvis_memory_proactive_watchlist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind is not None and bind.dialect.name == "postgresql"
    json_t = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()

    op.create_table(
        "research_documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("content_json", json_t, nullable=False, server_default=sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_documents_user_id", "research_documents", ["user_id"], unique=False)
    op.create_index("ix_research_documents_org_type", "research_documents", ["organization_id", "type"], unique=False)
    op.create_index("ix_research_documents_created", "research_documents", ["created_at"], unique=False)

    op.create_table(
        "govt_schemes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("sector", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("scheme_name", sa.Text(), nullable=False),
        sa.Column("eligibility", sa.Text(), nullable=True),
        sa.Column("subsidy_amount", sa.Text(), nullable=True),
        sa.Column("application_process", sa.Text(), nullable=True),
        sa.Column("deadline", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("content_json", json_t, nullable=False, server_default=sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_govt_schemes_user", "govt_schemes", ["user_id"], unique=False)
    op.create_index("ix_govt_schemes_org_sector", "govt_schemes", ["organization_id", "sector"], unique=False)
    op.create_index("ix_govt_schemes_created", "govt_schemes", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_govt_schemes_created", table_name="govt_schemes")
    op.drop_index("ix_govt_schemes_org_sector", table_name="govt_schemes")
    op.drop_index("ix_govt_schemes_user", table_name="govt_schemes")
    op.drop_table("govt_schemes")
    op.drop_index("ix_research_documents_created", table_name="research_documents")
    op.drop_index("ix_research_documents_org_type", table_name="research_documents")
    op.drop_index("ix_research_documents_user_id", table_name="research_documents")
    op.drop_table("research_documents")
