"""Self-Evolution Phase 2: causal graph + online learning + domain registry tables.

Adds:
- ``causal_edges``         (cause→effect with running mean / variance / confidence)
- ``feature_archive``      (daily archive of computed features, idempotent per day)
- ``predictions_pending``  (predict-now-resolve-later for the online learner)
- ``domain_definitions``   (registered domain plugins)

Revision ID: 0073_self_evolution_phase2
Revises: 0072_ml_learning_tables
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0073_self_evolution_phase2"
down_revision: Union[str, Sequence[str], None] = "0072_ml_learning_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type(is_pg: bool):
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def _json_default(is_pg: bool):
    return sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower() if bind is not None else "postgresql"
    is_pg = dialect == "postgresql"
    json_t = _json_type(is_pg)
    json_d = _json_default(is_pg)

    op.create_table(
        "causal_edges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("cause_variable", sa.String(length=128), nullable=False),
        sa.Column("effect_variable", sa.String(length=128), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sum_strength", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sum_strength_sq", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_payload", json_t, nullable=False, server_default=json_d),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "cause_variable",
            "effect_variable",
            name="uq_causal_edges_scope",
        ),
    )
    op.create_index(
        "ix_causal_edges_cause", "causal_edges", ["cause_variable"], unique=False
    )
    op.create_index(
        "ix_causal_edges_effect", "causal_edges", ["effect_variable"], unique=False
    )
    op.create_index(
        "ix_causal_edges_organization_id",
        "causal_edges",
        ["organization_id"],
        unique=False,
    )

    op.create_table(
        "feature_archive",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("feature_name", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("payload", json_t, nullable=False, server_default=json_d),
        sa.Column("captured_date", sa.Date(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "scope",
            "feature_name",
            "captured_date",
            name="uq_feature_archive_daily",
        ),
    )
    op.create_index(
        "ix_feature_archive_organization_id",
        "feature_archive",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_feature_archive_scope_name",
        "feature_archive",
        ["scope", "feature_name"],
        unique=False,
    )
    op.create_index(
        "ix_feature_archive_captured_date",
        "feature_archive",
        ["captured_date"],
        unique=False,
    )

    op.create_table(
        "predictions_pending",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("model_version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("action_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("action_type", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("features_json", json_t, nullable=False, server_default=json_d),
        sa.Column("predicted_outcome", json_t, nullable=False, server_default=json_d),
        sa.Column(
            "predicted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolve_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_outcome", json_t, nullable=False, server_default=json_d),
        sa.Column("accuracy_score", sa.Float(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_predictions_pending_model_name",
        "predictions_pending",
        ["model_name"],
        unique=False,
    )
    op.create_index(
        "ix_predictions_pending_resolved",
        "predictions_pending",
        ["resolved"],
        unique=False,
    )
    op.create_index(
        "ix_predictions_pending_resolve_after",
        "predictions_pending",
        ["resolve_after"],
        unique=False,
    )
    op.create_index(
        "ix_predictions_pending_action_id",
        "predictions_pending",
        ["action_id"],
        unique=False,
    )

    op.create_table(
        "domain_definitions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("models", json_t, nullable=False, server_default=json_d),
        sa.Column("features", json_t, nullable=False, server_default=json_d),
        sa.Column("tables", json_t, nullable=False, server_default=json_d),
        sa.Column("prompts", json_t, nullable=False, server_default=json_d),
        sa.Column("policies", json_t, nullable=False, server_default=json_d),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "registered_at",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_domain_definitions_name"),
    )
    op.create_index(
        "ix_domain_definitions_is_active",
        "domain_definitions",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_domain_definitions_is_active", table_name="domain_definitions")
    op.drop_table("domain_definitions")

    op.drop_index("ix_predictions_pending_action_id", table_name="predictions_pending")
    op.drop_index("ix_predictions_pending_resolve_after", table_name="predictions_pending")
    op.drop_index("ix_predictions_pending_resolved", table_name="predictions_pending")
    op.drop_index("ix_predictions_pending_model_name", table_name="predictions_pending")
    op.drop_table("predictions_pending")

    op.drop_index("ix_feature_archive_captured_date", table_name="feature_archive")
    op.drop_index("ix_feature_archive_scope_name", table_name="feature_archive")
    op.drop_index("ix_feature_archive_organization_id", table_name="feature_archive")
    op.drop_table("feature_archive")

    op.drop_index("ix_causal_edges_organization_id", table_name="causal_edges")
    op.drop_index("ix_causal_edges_effect", table_name="causal_edges")
    op.drop_index("ix_causal_edges_cause", table_name="causal_edges")
    op.drop_table("causal_edges")
