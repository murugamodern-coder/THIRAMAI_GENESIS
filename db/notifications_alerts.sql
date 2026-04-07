-- Notifications + debt due dates for workers/alert_system.py
-- Apply after db/db_schema.sql and db/auth_rbac.sql:
--   psql "$DATABASE_URL" -f db/notifications_alerts.sql

ALTER TABLE debts ADD COLUMN IF NOT EXISTS due_date DATE;

CREATE TABLE IF NOT EXISTS notifications (
    id                BIGSERIAL PRIMARY KEY,
    organization_id   BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    kind              VARCHAR(64) NOT NULL,
    severity          VARCHAR(16) NOT NULL DEFAULT 'warning',
    title             TEXT NOT NULL,
    body              TEXT NOT NULL,
    reference_type    VARCHAR(64),
    reference_id      BIGINT,
    payload           JSONB NOT NULL DEFAULT '{}',
    dedupe_key        VARCHAR(256) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at           TIMESTAMPTZ,
    CONSTRAINT uq_notifications_org_dedupe UNIQUE (organization_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_notifications_org_created
    ON notifications (organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_kind ON notifications (kind);
