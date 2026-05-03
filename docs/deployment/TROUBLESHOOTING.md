# Deployment troubleshooting

## Missing `ai_decisions` table

**Error:** `relation "ai_decisions" does not exist`

**Cause:** Database schema is behind the application — the `0078_add_ai_decisions_table` migration has not been applied (the ORM model already lives in `core/db/models.py` as `AiDecision`).

**Fix:** The `web` container image must include `alembic/versions/0078_add_ai_decisions_table.py`. If you added the file only on the host, **rebuild `web`** before upgrading:

```powershell
docker compose -f docker-compose.production.yml --env-file .env.production build web
docker compose -f docker-compose.production.yml --env-file .env.production up -d web

docker compose -f docker-compose.production.yml --env-file .env.production exec web alembic upgrade head

docker compose -f docker-compose.production.yml --env-file .env.production exec -T db psql -U thiramai -d thiramai -c "\d ai_decisions"

.\scripts\test_decision_api.ps1
```

Or run `.\scripts\apply_ai_decisions_migration.ps1` from the repository root (still requires the rebuilt image so `alembic upgrade head` sees revision 0078).

**Alternative:** Run Alembic on the host with `DATABASE_URL` pointing at Postgres (e.g. published port), from the repo root: `alembic upgrade head`.

**If the migration file is missing:** restore `alembic/versions/0078_add_ai_decisions_table.py` from source control, or create a new revision with `alembic revision -m "add_ai_decisions_table"` and align the upgrade DDL with the `AiDecision` model in `core/db/models.py`.

After upgrading, set `THIRAMAI_EXPECTED_DB_REVISION=0078_add_ai_decisions_table` in `.env.production` (or rely on the default in `core/migration_head.py`) and recreate the `web` container if you pass that variable explicitly in Compose.

Migration **0078** skips creating the table if `public.ai_decisions` already exists (then applies RLS alignment only), so you can stamp Alembic forward without dropping a manually created table.
