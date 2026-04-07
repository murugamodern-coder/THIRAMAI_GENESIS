-- Immutable security / compliance audit trail (services.audit_log).
-- Apply: psql "$DATABASE_URL" -f db/system_audit_logs.sql

CREATE TABLE IF NOT EXISTS system_audit_logs (
    id                  BIGSERIAL PRIMARY KEY,
    organization_id     BIGINT REFERENCES organizations (id) ON DELETE SET NULL,
    user_id             BIGINT REFERENCES users (id) ON DELETE SET NULL,
    action              VARCHAR(64) NOT NULL,
    outcome             VARCHAR(32) NOT NULL DEFAULT 'success',
    resource_type       VARCHAR(64),
    client_ip           VARCHAR(45),
    user_agent          TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_system_audit_logs_org_created
    ON system_audit_logs (organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_system_audit_logs_action_created
    ON system_audit_logs (action, created_at DESC);
