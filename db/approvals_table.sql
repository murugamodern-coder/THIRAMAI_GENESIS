-- HITL approvals (PostgreSQL). Replaces vault/pending_approvals.json.
-- Apply: psql "$DATABASE_URL" -f db/approvals_table.sql

CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid (),
    organization_id BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    created_by BIGINT REFERENCES users (id) ON DELETE SET NULL,
    approved_by BIGINT REFERENCES users (id) ON DELETE SET NULL,
    risk_tier TEXT NOT NULL DEFAULT 'high',
    summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_approvals_organization_id ON approvals (organization_id);
CREATE INDEX IF NOT EXISTS ix_approvals_status ON approvals (status);
CREATE INDEX IF NOT EXISTS ix_approvals_org_status ON approvals (organization_id, status);
