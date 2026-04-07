-- Factory Operating System: project lifecycle, staff assignments, billing pause on Stage-2 machine failure.
-- psql "$DATABASE_URL" -f db/factory_os.sql

CREATE TABLE IF NOT EXISTS factory_billing_hold (
    organization_id   BIGINT PRIMARY KEY REFERENCES organizations (id) ON DELETE CASCADE,
    billing_paused    BOOLEAN NOT NULL DEFAULT false,
    pause_reason      TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_stages (
    id                  BIGSERIAL PRIMARY KEY,
    organization_id     BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    project_name        TEXT NOT NULL,
    current_stage       INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    priority            INTEGER NOT NULL DEFAULT 0,
    asset_id            BIGINT REFERENCES assets (id) ON DELETE SET NULL,
    revival_cost_inr    NUMERIC(18, 2),
    machine_failed      BOOLEAN NOT NULL DEFAULT false,
    extra               JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_stages_org ON project_stages (organization_id, current_stage);
CREATE INDEX IF NOT EXISTS idx_project_stages_org_status ON project_stages (organization_id, status);

CREATE TABLE IF NOT EXISTS project_staff_assignments (
    id                  BIGSERIAL PRIMARY KEY,
    project_stage_id    BIGINT NOT NULL REFERENCES project_stages (id) ON DELETE CASCADE,
    user_id             BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role_note           TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_staff_user UNIQUE (project_stage_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_project_staff_project ON project_staff_assignments (project_stage_id);
CREATE INDEX IF NOT EXISTS idx_project_staff_user ON project_staff_assignments (user_id);
