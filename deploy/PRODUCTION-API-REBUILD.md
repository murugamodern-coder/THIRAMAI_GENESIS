# Fix: production missing `/ai/goal` (stale API image)

## Cause

`docker-compose.production.yml` previously declared **`web`** with **`image: thiramai-app:…` only** (no **`build`**). Running `docker compose build web` **did not rebuild** the API from git; Compose kept pulling or reusing whatever `thiramai-app:latest` was tagged on the host — often **missing current routers** such as **`POST /ai/goal`**.

The compose file now includes **`build:`** for **`web`** so **`docker compose build web`** builds from the repo **`Dockerfile`**.

## Code verification (repo)

- **`api/routes/registry.py`** — `from api.routes.ai_goal import router as ai_goal_router` and `app.include_router(ai_goal_router)`.
- **`api/routes/ai_goal.py`** — exists; defines **`/ai`** autonomous surface.

## On the production server

From the deployment clone (adjust path):

```bash
cd /root/thiramai-app   # or your checkout
git pull
./deploy/scripts/rebuild-web-production.sh
```

Or manually:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production build --no-cache web
docker compose -f docker-compose.production.yml --env-file .env.production up -d --force-recreate web
```

## Verify OpenAPI

```bash
curl -sfS https://app.thiramai.co.in/openapi.json | grep '/ai/goal'
# or
curl -sfS https://app.thiramai.co.in/openapi.json | jq '.paths["/ai/goal"]'
```

Expect a **`post`** operation object.

## Test `/ai/goal`

Requires JWT (**owner**, **manager**, or **admin**):

```bash
curl -sS -X POST "https://app.thiramai.co.in/ai/goal" \
  -H "Authorization: Bearer $JWT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal":"Production rebuild verification goal"}'
```

Expect **200** with `job_id` (or **409** idempotent replay).

Then poll **`GET /ai/status?job_id=…`** with the same bearer token.

## Workers / SQLite

After the API matches git, jobs execute per **`THIRAMAI_GOAL_WORKER_DISPATCH`** and SQLite layout in **`thiramai/data/`**. See **`docker-compose.goal-worker.yml`** if goals are dispatched to workers.
