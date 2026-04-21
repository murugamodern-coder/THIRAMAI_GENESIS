# Tenant isolation (OWASP A01)

Thiramai is a multi-tenant product: each business is an `organizations` row, and most operational data carries `organization_id` (or `org_id` in some legacy columns). **Broken object level authorization (BOLA / IDOR)** is prevented by combining JWT tenant context, membership checks, and org-scoped queries—not by trusting client-supplied organization identifiers.

## How isolation works

1. **Authentication (`api/dependencies.py`)**  
   The access JWT carries `active_org_id` / `org_id` and `role`. `get_current_user` decodes the token, loads the user, and resolves the **active membership** for that organization. If the user is not an active member of the claimed org, the request fails with **401**. Disabled organizations return **403**.

2. **Authorization**  
   `require_roles` and `require_permission` gate capabilities using the role embedded in the JWT (which must match the membership’s role in the database). This is orthogonal to tenant scope but prevents low-privilege roles from hitting sensitive routes.

3. **Application / service layer**  
   Routes must pass **`CurrentUser.organization_id`** (or an equivalent explicitly derived from the JWT-backed principal) into services. Services should filter mutations and reads with that id. Many inventory flows use `services.inventory_phase2_service` helpers that load rows by primary key and then compare `row.organization_id` to the caller’s org—wrong-tenant access surfaces as business errors (**400**) or empty results rather than a successful cross-tenant read.

4. **Database**  
   Foreign keys tie rows to `organizations.id`. There is **no row-level security policy** in the application schema that automatically strips cross-tenant SELECTs; correctness depends on the query always including `organization_id = :active_org`. Treat the database as the last line of structural integrity (FKs), not the primary enforcement layer for IDOR.

## Dev-only behavior

When `THIRAMAI_AUTH_DISABLED=1` and **no** `Authorization` header is sent, `get_current_user` returns a synthetic dev principal. In non-production environments, **`X-THIRAMAI-DEV-ORG-ID`** can override the dev org **only in that bypass path**. It does **not** override a valid Bearer JWT: the JWT’s active organization always wins.

There is **no** supported `X-Org-ID` header for production tenant switching; do not implement one without explicit membership validation and audit.

## Automated audit

- Tests: `tests/test_tenant_isolation.py` (in-memory SQLite, patched `get_session_factory` across modules that bind it at import time).
- Runner: `scripts/run_tenant_audit.sh` produces `reports/tenant_isolation_report.xml` (JUnit).

The suite today focuses on **high-risk, org-scoped HTTP surfaces** (inventory, audit, control-plane jobs/alerts/reorder, tenancy, analytics summary) plus **IDOR-style probes** on inventory item ids. Extend the same patterns when adding routers that touch tenant tables.

## Adding a new endpoint safely

1. Depend on **`get_current_user`** (or a stricter `require_permission` / `require_roles` built on it).
2. Use **`_user.organization_id`** for every read/write to tenant tables. Never take `organization_id` from unchecked query/body fields alone.
3. For path parameters (`{id}`), load by id **and** constrain by `organization_id` in the same query or verify `row.organization_id == _user.organization_id` before returning or mutating.
4. If the route accepts an explicit `organization_id` (e.g. preview by org), call **`ensure_org_membership`** before using it.
5. Prefer returning **404** or a generic **400** for cross-tenant mismatches instead of echoing the other tenant’s payload.

## Code reviewer checklist

- [ ] Route uses `CurrentUser` from JWT, not a raw org id from the client.
- [ ] All SQLAlchemy queries for tenant tables include `organization_id` (or join through a table that is already org-scoped).
- [ ] Mutations that accept resource ids verify org ownership after load.
- [ ] No “load by id only” access patterns for shared numeric id spaces without org filter.
- [ ] Dev bypass (`THIRAMAI_AUTH_DISABLED`) and `X-THIRAMAI-DEV-ORG-ID` are not relied on for security in production.
- [ ] New services that import `get_session_factory` at module level are covered in **integration tests** that patch the same module copy the route stack uses (see `tests/test_tenant_isolation.py` `_patch_session_factories`).
