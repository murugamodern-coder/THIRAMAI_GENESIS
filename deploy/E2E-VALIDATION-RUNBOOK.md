# THIRAMAI — End-to-end production validation

Run these checks **on a machine that can reach the deployment** (bastion, laptop with VPN, or CI) after every release.

Default URL:

```bash
export BASE_URL=https://app.thiramai.co.in
```

Helpers:

- Bash: **`deploy/scripts/e2e-validate-production.sh`**
- PowerShell: **`deploy/scripts/e2e-validate-production.ps1`**

---

## Step 1 — Service status (on the **host**)

```bash
docker compose -f docker-compose.production.yml ps
sudo systemctl status nginx --no-pager
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health/live
```

Expect: compose services **running**, nginx **active**, loopback API **200**.

*(Local developer Windows without Docker/Linux cannot satisfy this step — use SSH to prod.)*

---

## Step 2 — Health (through Nginx)

```bash
curl -sfS "${BASE_URL}/health/live"
curl -sfS "${BASE_URL}/health/ready"
```

Expect: **HTTP 200**, JSON (`status`, checks on `/health/ready`).

---

## Step 3 — Frontend load

```bash
curl -sfSIL "${BASE_URL}/" | head -20
curl -sfS "${BASE_URL}/static/js/" 2>/dev/null | head -c 200 || true
```

Expect: **200** on `/` (redirect or HTML). Open DevTools on the site: **no red console errors** (manual).

---

## Step 4 — API flow (autonomous goals)

**Requires:** JWT with role **owner**, **manager**, or **admin** (`Authorization: Bearer …`).

```bash
TOKEN="…"   # from POST /auth/login

curl -sfS -X POST "${BASE_URL}/ai/goal" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"goal":"Test system health check — production validation"}'

JOB_ID="…"   # from JSON job_id

curl -sfS "${BASE_URL}/ai/status?job_id=${JOB_ID}" \
  -H "Authorization: Bearer $TOKEN"
```

Poll until `status` is `completed` or `failed`.

**Precondition:** OpenAPI must list **`POST /ai/goal`**. Verify:

```bash
curl -sfS "${BASE_URL}/openapi.json" | jq -e '.paths["/ai/goal"].post' >/dev/null && echo "goal route present"
```

If this fails, the API image is **not** built from the current THIRAMAI Genesis tree (or `api.routes.ai_goal` failed to register). **Redeploy** the latest backend image before continuing.

---

## Step 5 — WebSocket (`/ai/logs/ws/{job_id}`)

```bash
# Example (requires websocat or wscat): pass access token as query param per API
websocat -v -t --header="Authorization: Bearer $TOKEN" \
  "${BASE_URL/https/wss}/ai/logs/ws/${JOB_ID}?token=${TOKEN}"
```

Expect: **101 Switching Protocols**, JSON log frames over time.

---

## Step 6 — Worker execution

```bash
docker compose -f docker-compose.production.yml logs --tail=80 web worker-jobs
# optional
docker compose -f docker-compose.goal-worker.yml logs --tail=80 goal-worker
```

Expect: jobs move from **pending** → **running** → terminal state; no infinite **pending** without worker when `THIRAMAI_GOAL_WORKER_DISPATCH=1`.

---

## Step 7 — SQLite (`goal_jobs.sqlite`)

On the host (or inside the container that mounts `thiramai/data`):

```bash
sqlite3 /path/to/thiramai/data/goal_jobs.sqlite "SELECT id,status,substr(goal,1,60) FROM jobs ORDER BY rowid DESC LIMIT 5;"
```

Expect: recent rows match UI/API job ids.

---

## Step 8 — Rate limits

Send ~40 rapid GETs to `/ai/status` (same job):

```bash
for i in $(seq 1 45); do curl -s -o /dev/null -w "%{http_code}\n" \
  "${BASE_URL}/ai/status?job_id=$JOB_ID" -H "Authorization: Bearer $TOKEN"; done | sort | uniq -c
```

Expect: mostly **200**; occasional **429** only under abuse. If normal polling hits **429**, raise **`burst`** or **`rate`** in `deploy/nginx/conf.d/10-thiramai-production.conf`.

---

## Step 9 — Error handling

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${BASE_URL}/ai/goal" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"goal":""}'
```

Expect: **422** or **400**, JSON **detail** (not stack traces in production). UI should show friendly message (manual).

---

## Step 10 — Final pass

Re-run steps 2–5 after any config change.

---

## Snapshot (automated probes, ${BASE_URL}=production)

| Check | Result |
|--------|--------|
| `GET /health/live` | **200**, JSON `{ "status": "alive", … }` |
| `GET /health/ready` | **200**, DB/Redis/Alembic OK |
| `GET /` | **200** |
| `openapi` contains `POST /ai/goal` | **Verify after deploy** — must be **true** for goals E2E |

---

## Remediation if `/ai/goal` is missing

1. Confirm repo **`api/routes/registry.py`** includes **`ai_goal_router`** (current Genesis mainline does).
2. Rebuild **`thiramai-app`** image from this repository and **`docker compose up -d`**.
3. Re-run OpenAPI precondition and Step 4.
