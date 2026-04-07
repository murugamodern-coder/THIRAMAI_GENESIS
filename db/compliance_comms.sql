-- Phase 5 compliance + comms (manual apply if not using Alembic 0005).
-- psql "$DATABASE_URL" -f db/compliance_comms.sql

CREATE TABLE IF NOT EXISTS compliance_cases (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category VARCHAR(32) NOT NULL,
    priority VARCHAR(32) NOT NULL DEFAULT 'normal',
    deadline DATE,
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    external_ref VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_compliance_cases_org_external_ref UNIQUE (organization_id, external_ref)
);
CREATE INDEX IF NOT EXISTS ix_compliance_cases_organization_id ON compliance_cases (organization_id);
CREATE INDEX IF NOT EXISTS ix_compliance_cases_deadline ON compliance_cases (deadline);
CREATE INDEX IF NOT EXISTS ix_compliance_cases_category ON compliance_cases (category);

CREATE TABLE IF NOT EXISTS comms_inbox (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    source VARCHAR(32) NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_summary TEXT NOT NULL,
    intelligence_tier VARCHAR(32),
    related_case_id BIGINT REFERENCES compliance_cases (id) ON DELETE SET NULL,
    message_id VARCHAR(512),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_comms_inbox_organization_id ON comms_inbox (organization_id);
CREATE INDEX IF NOT EXISTS ix_comms_inbox_related_case_id ON comms_inbox (related_case_id);
CREATE INDEX IF NOT EXISTS ix_comms_inbox_intelligence_tier ON comms_inbox (intelligence_tier);
