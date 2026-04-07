-- Phase 4 Business OS (manual apply if not using Alembic 0004_business_depth_expansion).
-- psql "$DATABASE_URL" -f db/business_depth.sql

ALTER TABLE departments ADD COLUMN IF NOT EXISTS lead_user_id BIGINT REFERENCES users (id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_departments_lead_user_id ON departments (lead_user_id);

ALTER TABLE inventory ADD COLUMN IF NOT EXISTS unit_cost_pre_tax NUMERIC(18, 2);

CREATE TABLE IF NOT EXISTS staff_profiles (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    organization_id BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    department_id BIGINT REFERENCES departments (id) ON DELETE SET NULL,
    basic_salary NUMERIC(18, 2) NOT NULL DEFAULT 0,
    joining_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_staff_profiles_user_org UNIQUE (user_id, organization_id)
);
CREATE INDEX IF NOT EXISTS ix_staff_profiles_organization_id ON staff_profiles (organization_id);
CREATE INDEX IF NOT EXISTS ix_staff_profiles_user_id ON staff_profiles (user_id);
CREATE INDEX IF NOT EXISTS ix_staff_profiles_department_id ON staff_profiles (department_id);

CREATE TABLE IF NOT EXISTS attendance_logs (
    id BIGSERIAL PRIMARY KEY,
    staff_id BIGINT NOT NULL REFERENCES staff_profiles (id) ON DELETE CASCADE,
    check_in TIMESTAMPTZ NOT NULL,
    check_out TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'present',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_attendance_logs_staff_id ON attendance_logs (staff_id);
CREATE INDEX IF NOT EXISTS ix_attendance_logs_check_in ON attendance_logs (check_in);

CREATE TABLE IF NOT EXISTS operational_expenses (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    expense_date DATE NOT NULL,
    category VARCHAR(64) NOT NULL,
    amount_inr NUMERIC(18, 2) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_operational_expenses_org_date ON operational_expenses (organization_id, expense_date);
