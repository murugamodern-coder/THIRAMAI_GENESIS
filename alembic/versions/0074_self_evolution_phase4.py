"""Self-Evolution Phase 4: self-architecture + Bayesian world model + meta-learning.

Adds:
- ``architecture_proposals``  (LLM-designed new modules, sandboxed before approval)
- ``world_state_snapshots``   (Bayesian belief vector + outcome forecasts per org)
- ``world_transition_edges``  (running transition counts between discretised states)
- ``meta_learning_records``   (feature importance, model choice, time-of-day, HPs)

Revision ID: 0074_self_evolution_phase4
Revises: 0073_self_evolution_phase2
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0074_self_evolution_phase4"
down_revision: Union[str, Sequence[str], None] = "0073_self_evolution_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type(is_pg: bool):
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def _json_default(is_pg: bool):
    return sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")


def _list_default(is_pg: bool):
    return sa.text("'[]'::jsonb") if is_pg else sa.text("'[]'")


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower() if bind is not None else "postgresql"
    is_pg = dialect == "postgresql"
    json_t = _json_type(is_pg)
    json_d = _json_default(is_pg)
    list_d = _list_default(is_pg)

    # ---- architecture_proposals ----
    op.create_table(
        "architecture_proposals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("proposed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("need_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("module_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("proposed_path", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("generated_code", sa.Text(), nullable=False, server_default=""),
        sa.Column("generated_tests", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="proposed"),
        sa.Column("sandbox_passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sandbox_exit_code", sa.Integer(), nullable=True),
        sa.Column("sandbox_log", sa.Text(), nullable=False, server_default=""),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True) if is_pg else sa.String(length=64), nullable=True),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_note", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("evidence", json_t, nullable=False, server_default=json_d),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_architecture_proposals_status",
        "architecture_proposals",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_architecture_proposals_organization_id",
        "architecture_proposals",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_architecture_proposals_created_at",
        "architecture_proposals",
        ["created_at"],
        unique=False,
    )

    # ---- world_state_snapshots ----
    op.create_table(
        "world_state_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("state_signature", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("state_vector", json_t, nullable=False, server_default=json_d),
        sa.Column("belief_distribution", json_t, nullable=False, server_default=json_d),
        sa.Column("outcome_predictions", json_t, nullable=False, server_default=json_d),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_version", sa.String(length=32), nullable=False, server_default="v2"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_world_state_snapshots_org_captured",
        "world_state_snapshots",
        ["organization_id", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_world_state_snapshots_signature",
        "world_state_snapshots",
        ["state_signature"],
        unique=False,
    )

    # ---- world_transition_edges ----
    op.create_table(
        "world_transition_edges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("from_state_signature", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("to_state_signature", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("transition_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome_aggregates", json_t, nullable=False, server_default=json_d),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "from_state_signature",
            "to_state_signature",
            name="uq_world_transition_edges_scope",
        ),
    )
    op.create_index(
        "ix_world_transition_edges_from",
        "world_transition_edges",
        ["from_state_signature"],
        unique=False,
    )
    op.create_index(
        "ix_world_transition_edges_to",
        "world_transition_edges",
        ["to_state_signature"],
        unique=False,
    )

    # ---- meta_learning_records ----
    op.create_table(
        "meta_learning_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("domain", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("record_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("payload", json_t, nullable=False, server_default=json_d),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_recommendation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meta_learning_records_org_domain",
        "meta_learning_records",
        ["organization_id", "domain"],
        unique=False,
    )
    op.create_index(
        "ix_meta_learning_records_record_type",
        "meta_learning_records",
        ["record_type"],
        unique=False,
    )
    op.create_index(
        "ix_meta_learning_records_recommended",
        "meta_learning_records",
        ["is_recommendation", "domain", "record_type"],
        unique=False,
    )

    # Suppress unused-warning for list_d in single-dialect builds.
    _ = list_d


def downgrade() -> None:
    op.drop_index("ix_meta_learning_records_recommended", table_name="meta_learning_records")
    op.drop_index("ix_meta_learning_records_record_type", table_name="meta_learning_records")
    op.drop_index("ix_meta_learning_records_org_domain", table_name="meta_learning_records")
    op.drop_table("meta_learning_records")

    op.drop_index("ix_world_transition_edges_to", table_name="world_transition_edges")
    op.drop_index("ix_world_transition_edges_from", table_name="world_transition_edges")
    op.drop_table("world_transition_edges")

    op.drop_index("ix_world_state_snapshots_signature", table_name="world_state_snapshots")
    op.drop_index("ix_world_state_snapshots_org_captured", table_name="world_state_snapshots")
    op.drop_table("world_state_snapshots")

    op.drop_index("ix_architecture_proposals_created_at", table_name="architecture_proposals")
    op.drop_index("ix_architecture_proposals_organization_id", table_name="architecture_proposals")
    op.drop_index("ix_architecture_proposals_status", table_name="architecture_proposals")
    op.drop_table("architecture_proposals")
