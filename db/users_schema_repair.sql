-- Idempotent repair for legacy ``users`` rows missing identity columns (PostgreSQL).
ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_id BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Indexes only when columns exist (repair may be applied on mixed schema states).
DO $thiramai_ix_users_repair$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'role_id'
  ) THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS ix_users_role_id ON public.users (role_id)';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'organization_id'
  ) THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS ix_users_organization_id ON public.users (organization_id)';
  END IF;
END
$thiramai_ix_users_repair$;

DO $thiramai_users_fk$
BEGIN
  ALTER TABLE users
    ADD CONSTRAINT fk_users_role
    FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE SET NULL;
EXCEPTION
  WHEN duplicate_object THEN NULL;
  WHEN undefined_table THEN NULL;
END
$thiramai_users_fk$;

DO $thiramai_users_org_fk$
BEGIN
  ALTER TABLE users
    ADD CONSTRAINT fk_users_organization
    FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE;
EXCEPTION
  WHEN duplicate_object THEN NULL;
  WHEN undefined_table THEN NULL;
END
$thiramai_users_org_fk$;
