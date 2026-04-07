-- Post-mortem / HITL learning (core/recursive_learning.py).
-- Apply: psql "$DATABASE_URL" -f db/learning_logs.sql

CREATE TABLE IF NOT EXISTS learning_logs (
    id                  BIGSERIAL PRIMARY KEY,
    organization_id     BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    approval_id         UUID REFERENCES approvals (id) ON DELETE SET NULL,
    outcome             VARCHAR(32) NOT NULL,
    action_type         VARCHAR(128) NOT NULL DEFAULT '',
    lesson_summary      TEXT NOT NULL DEFAULT '',
    context             JSONB NOT NULL DEFAULT '{}'::jsonb,
    result              JSONB NOT NULL DEFAULT '{}'::jsonb,
    user_feedback       TEXT,
    resolved_by_user_id BIGINT REFERENCES users (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_learning_logs_org_created
    ON learning_logs (organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_learning_logs_org_outcome
    ON learning_logs (organization_id, outcome);
