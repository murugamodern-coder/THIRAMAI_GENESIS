-- Enterprise idempotency + DB-backed job queue (API ↔ worker processes).
-- Apply after core schema: psql "$DATABASE_URL" -f db/idempotency_and_jobs.sql

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key VARCHAR(512) PRIMARY KEY,
    action_type     VARCHAR(128) NOT NULL DEFAULT '',
    meta            JSONB NOT NULL DEFAULT '{}',
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_completed
    ON idempotency_keys (completed_at)
    WHERE completed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_created_pending
    ON idempotency_keys (created_at)
    WHERE completed_at IS NULL;

CREATE TABLE IF NOT EXISTS background_jobs (
    id                BIGSERIAL PRIMARY KEY,
    job_type          VARCHAR(64) NOT NULL,
    organization_id   BIGINT REFERENCES organizations (id) ON DELETE CASCADE,
    idempotency_key   VARCHAR(512) NOT NULL,
    payload           JSONB NOT NULL DEFAULT '{}',
    status            VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts          INTEGER NOT NULL DEFAULT 0,
    max_attempts      INTEGER NOT NULL DEFAULT 5,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_background_jobs_pending
    ON background_jobs (status, id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_background_jobs_org_created
    ON background_jobs (organization_id, created_at DESC);
