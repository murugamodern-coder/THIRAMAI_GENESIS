# Database setup notes

## PostgreSQL user configuration

The application supports a custom PostgreSQL role via `POSTGRES_USER` (Docker / cloud).

**Typical production Compose values:**

```bash
POSTGRES_USER=thiramai
POSTGRES_DB=thiramai
```

Use the **same** user in `DATABASE_URL` and in `POSTGRES_USER`.

## Row level security (RLS)

Migration **0047** (`0047_add_rls_tenant_isolation`) enables RLS on multi-tenant tables. The
`superuser_bypass` policy targets the **role that runs migrations** (`session_user`), not a
hardcoded `postgres` role, so clusters where `POSTGRES_USER=thiramai` and the `postgres` role
was never created work without changes.

### "role postgres does not exist"

This appeared in older revisions of 0047 that used `TO postgres` in `CREATE POLICY`. **Fix:**

1. **New environments:** use the current `0047_add_rls_tenant_isolation.py` and run:

   ```bash
   alembic upgrade head
   ```

2. **Already stamped with broken policies or failed mid-migration:** upgrade through **0077**
   (`0077_fix_rls_superuser_bypass_role`), which recreates `superuser_bypass` for each table
   that still has that policy, using the **current** database session role (again via
   `quote_ident(session_user)`).

   ```bash
   docker compose -f docker-compose.production.yml --env-file .env.production exec -T web alembic upgrade head
   ```

### Manual fallback (discouraged)

Creating an empty `postgres` role only papers over the policy mismatch and does not match
`POSTGRES_USER` for bypass when the app connects as `thiramai`. Prefer the migrations above.

## Revision note: why not "0048_fix_rls"?

The repo already uses **0048** for two parallel branches (`0048_agent_tasks`,
`0048_user_runtime_config`) merged by **0049**. The repair migration is **0077**, chained
after the current head **0076**.
