-- Per-tenant departments (default "General" on provision). Apply:
--   psql "$DATABASE_URL" -f db/departments.sql

CREATE TABLE IF NOT EXISTS departments (
    id                BIGSERIAL PRIMARY KEY,
    organization_id   BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_departments_org_name UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_departments_org ON departments (organization_id);
