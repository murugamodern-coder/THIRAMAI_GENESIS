-- THIRAMAI RBAC + Identity (run after db/db_schema.sql so `organizations` exists).
-- Roles are scoped per organization (`org_id`). Re-run safe: IF NOT EXISTS / ON CONFLICT.

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free';

CREATE TABLE IF NOT EXISTS roles (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    CONSTRAINT uq_roles_org_id_name UNIQUE (org_id, name)
);

CREATE INDEX IF NOT EXISTS ix_roles_org_id ON roles (org_id);

CREATE TABLE IF NOT EXISTS permissions (
    id BIGSERIAL PRIMARY KEY,
    role_id BIGINT NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
    resource TEXT NOT NULL,
    action TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_permissions_role_id ON permissions (role_id);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    organization_id BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL REFERENCES roles (id) ON DELETE RESTRICT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_users_email UNIQUE (email)
);

CREATE INDEX IF NOT EXISTS ix_users_organization_id ON users (organization_id);
CREATE INDEX IF NOT EXISTS ix_users_role_id ON users (role_id);

-- Seed the four roles for the first organization only (app startup also seeds per org).
INSERT INTO roles (org_id, name, level)
SELECT o.id, v.name, v.level
FROM organizations o
CROSS JOIN (
    VALUES
        ('owner', 1),
        ('manager', 2),
        ('supervisor', 3),
        ('worker', 4)
) AS v (name, level)
WHERE o.id = (SELECT id FROM organizations ORDER BY id LIMIT 1)
ON CONFLICT (org_id, name) DO NOTHING;

-- Example permissions (first org’s roles only).
INSERT INTO permissions (role_id, resource, action)
SELECT r.id, 'billing', 'execute'
FROM roles r
WHERE r.name = 'owner'
  AND r.org_id = (SELECT id FROM organizations ORDER BY id LIMIT 1)
  AND NOT EXISTS (
      SELECT 1 FROM permissions p WHERE p.role_id = r.id AND p.resource = 'billing' AND p.action = 'execute'
  );

INSERT INTO permissions (role_id, resource, action)
SELECT r.id, 'billing', 'execute'
FROM roles r
WHERE r.name = 'manager'
  AND r.org_id = (SELECT id FROM organizations ORDER BY id LIMIT 1)
  AND NOT EXISTS (
      SELECT 1 FROM permissions p WHERE p.role_id = r.id AND p.resource = 'billing' AND p.action = 'execute'
  );

INSERT INTO permissions (role_id, resource, action)
SELECT r.id, 'inventory', 'read'
FROM roles r
WHERE r.name IN ('owner', 'manager', 'supervisor')
  AND r.org_id = (SELECT id FROM organizations ORDER BY id LIMIT 1)
  AND NOT EXISTS (
      SELECT 1 FROM permissions p WHERE p.role_id = r.id AND p.resource = 'inventory' AND p.action = 'read'
  );

INSERT INTO permissions (role_id, resource, action)
SELECT r.id, 'production', 'write'
FROM roles r
WHERE r.name IN ('owner', 'manager', 'supervisor')
  AND r.org_id = (SELECT id FROM organizations ORDER BY id LIMIT 1)
  AND NOT EXISTS (
      SELECT 1 FROM permissions p WHERE p.role_id = r.id AND p.resource = 'production' AND p.action = 'write'
  );
