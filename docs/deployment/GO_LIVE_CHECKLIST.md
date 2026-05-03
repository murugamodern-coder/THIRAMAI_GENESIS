# Final Go-Live Checklist

Complete this checklist before declaring the system **LIVE**.

Use the **published web port** from Compose when it differs from `WEB_PORT` in `.env.production`:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production port web 8000
# Example: 127.0.0.1:18080  -> BASE is http://127.0.0.1:18080
```

Or set **`THIRAMAI_GO_LIVE_BASE_URL`** once for all scripts.

---

## Pre-Deployment

- [ ] All tests passing

```bash
pytest tests/ -q
# Expected: 1264 passed (skips optional)
```

- [ ] Environment configured

```bash
grep -E "THIRAMAI_DECISION_AB_TEST|POOL_SIZE|JWT_SECRET_KEY" .env.production
# Expected: required settings present
```

- [ ] Docker services healthy

```bash
python scripts/check_docker_status.py
# Expected: all services OK

# Optional: wait up to 300s
python scripts/check_docker_status.py --wait --timeout 300
```

## System Health

- [ ] Health endpoints responding

```bash
./scripts/quick_health_check.sh
# Expected: live + ready OK; PolicyEngine + circuit lines printed
```

- [ ] PolicyEngine operational

```bash
# Replace BASE with your URL (see port command above)
curl -sS "${BASE}/health/ready" | jq '.checks.policy_engine.status'
# Expected: "healthy" or "degraded"
```

- [ ] Circuit breaker closed (or half-open while recovering)

```bash
curl -sS "${BASE}/health/ready" | jq '.checks.policy_engine.circuit_breaker.state'
# Expected: "closed" (or "half_open" briefly)
```

## Functional Tests

- [ ] Authentication working

```bash
curl -sS -X POST "${BASE}/auth/login" \
  -d "username=admin_king" -d "password=thiramai_2026"
# Expected: JSON with access_token (use real credentials in production)
```

- [ ] Decision API working

```bash
TOKEN="<from login>"
curl -sS -X POST "${BASE}/chat/decision" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"message":"test"}'
# Expected: HTTP 200 with decision payload
```

- [ ] AI brain verified

From the decision response, expect **`decision.data.decision_brain_source`** to be **`policy_engine`** or governed fallback (e.g. **`safe_fallback`**) per your policy settings.

## Live Test

- [ ] Full live test passing

```bash
./scripts/run_local_live_test.sh
python scripts/analyze_test_results.py --file local_live_test_results.txt
# Expected: no critical failures in analyzer; log shows health/auth/decision checks
```

## Post-Deployment

- [ ] Make several test decisions in a safe environment
- [ ] Verify persistence / audit expectations for your org
- [ ] Quality metrics (when enabled)

```bash
curl -sS "${BASE}/monitoring/ai-quality" \
  -H "Authorization: Bearer ${TOKEN}"
```

- [ ] Monitor logs briefly

```bash
docker compose -f docker-compose.production.yml --env-file .env.production logs --tail 100 web
```

## Final Verification

- [ ] No unexpected errors in web logs
- [ ] Metrics endpoint responds (if exposed): `${BASE}/metrics`
- [ ] PolicyEngine stable after warm-up
- [ ] Database migrations at expected revision (see compose env / `EXPECTED_ALEMBIC_REVISION`)

## Sign-Off

| Field | Value |
|-------|--------|
| **System Status** | LIVE / NOT READY |
| **Verified By** | |
| **Date** | |
| **Version / tag** | |
| **Notes** | |
