-- Scope existing global `roles` rows to organizations (THIRAMAI roadmap: org_id on roles).
-- Run once against a DB that already has `roles` without `org_id`.
-- Requires at least one row in `organizations`.

ALTER TABLE roles ADD COLUMN IF NOT EXISTS org_id BIGINT REFERENCES organizations (id) ON DELETE CASCADE;

UPDATE roles r
SET org_id = (SELECT id FROM organizations ORDER BY id LIMIT 1)
WHERE r.org_id IS NULL;

ALTER TABLE roles ALTER COLUMN org_id SET NOT NULL;

ALTER TABLE roles DROP CONSTRAINT IF EXISTS uq_roles_name;
ALTER TABLE roles DROP CONSTRAINT IF EXISTS roles_name_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_org_id_name ON roles (org_id, name);
