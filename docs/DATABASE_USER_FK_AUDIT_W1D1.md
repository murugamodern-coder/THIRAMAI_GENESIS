# Week 1 Day 1 — User reference columns audit (`core/db/models.py`)

## Scope

Columns matching: `user_id`, `resolved_by_user_id`, `created_by`, `created_by_user_id`, `updated_by`, `lead_user_id`, and any `ForeignKey("users.id"`.

## Summary counts (automated / manual review)

- **`ForeignKey("users.id` references in `models.py`:** 84
- **ORM `__tablename__` entries:** 100+ model tables (see `core/db/models.py`)
- **Audit date:** 2026-04-25

## Type policy (target)

- **Primary key `users.id`:** `BigInteger` (SQLite uses `Integer` variant in dev).
- **Tenant-scoped rows:** `organization_id` + `user_id` where both apply; always filter by org in app and RLS where enabled.
- **Known risk area (addressed in migration `0069_fix_learning_logs_user_id_integrity`):** `learning_logs.user_id` must be **bigint** in PostgreSQL to match `users.id` and ORM. Any **uuid-typed** `user_id` in legacy DBs is normalized in that migration.

## Notable columns

| Area | Column(s) | Expected type | FK / index |
| --- | --- | --- | --- |
| `learning_logs` | `user_id`, `resolved_by_user_id` | `BigInteger` | FK to `users.id`; indexes in `0069` + `0007` |
| `system_audit_logs` | `user_id` | `BigInteger` | FK; `ix_system_audit_logs_user_created` (0007) |
| `stock_movements` | `created_by_user_id` | `BigInteger` | FK to `users.id` |
| `approvals` | `created_by` | `BigInteger` | FK to `users.id` (see model) |
| `departments` | `lead_user_id` | `BigInteger` | FK to `users.id` |
| `opportunities` | `user_id` (no `organization_id` on table) | `BigInteger` | Per-user + status index in `0070` |

## `automation_rules`

- Schema is **per-user** (`user_id`); there is **no** `organization_id` or `is_active` column — the flag is **`enabled`**. Index `(user_id, enabled)` already exists as `ix_automation_rules_user_enabled` when the table is created; `0070` adds a parallel name only if the legacy name is missing.

## Legacy `inventory` vs `inventory_items`

- **`inventory`:** no `created_at` — cannot support `(organization_id, created_at)`; use **`inventory_items`** for time-ordered tenant lists (`idx_w1d1_inventory_items_org_created_desc` in `0070`).
- **`inventory`:** optional `idx_w1d1_inventory_org` on `organization_id` for tenant filters.

## Action items (completed this pass)

1. Migration **`0069`:** `learning_logs` type alignment + `idx_learning_logs_resolved_by` + conditional `idx_learning_logs_user_org`.
2. Migration **`0070`:** performance indexes for invoices, conversations, action runs, opportunities, etc.
