# Runbook: PolicyEngine / DecisionBrainV2

**Severity:** varies (warning when falling back to legacy; critical if strict mode breaks `/chat/decision`)  
**Metrics:** `thiramai_policy_engine_failures_total`, `thiramai_decision_route_total{engine="policy_engine|legacy|safe_fallback"}`, `thiramai_policy_engine_circuit_state`, `thiramai_safe_fallback_decisions_total`  
**Health:** `GET /health/ready` → `checks.policy_engine` (fails readiness when `THIRAMAI_HEALTH_REQUIRE_POLICY_ENGINE` is set)

## Circuit breaker + safe fallback

- `services/policy_engine_wrapper.py` wraps `PolicyEngine.decide` with a **process-local** circuit breaker (counts failures, opens → short-circuit, half-open after timeout).
- When `THIRAMAI_POLICY_SAFE_FALLBACK=true` (default), PolicyEngine errors (including circuit open) produce a V2 **`safe_fallback`** payload (`no_action` → executor `noop`) **before** Groq legacy.
- `THIRAMAI_DISABLE_LEGACY_FALLBACK=true` still **fails closed** (raises) on Policy errors — no Groq, no safe fallback path that hides outages if you need strict semantics.

## Symptoms

- Logs: `PolicyEngine.decide failed` then legacy fallback (unless `THIRAMAI_DISABLE_LEGACY_FALLBACK=true`).
- `/chat/decision` returns 503: `decision unavailable: V2 bundle missing and legacy fallback disabled`.
- Prometheus: `rate(thiramai_policy_engine_failures_total[5m])` elevated.

## Configuration checks

```bash
docker compose exec web env | grep -E 'DECISION_AB|POLICY_ENGINE|DISABLE_LEGACY|HEALTH_REQUIRE_POLICY'
```

Production intent:

- `THIRAMAI_DECISION_AB_TEST=false` — 100% PolicyEngine path in `DecisionBrainV2`.
- `THIRAMAI_POLICY_ENGINE_PCT=100` — only relevant when A/B is **enabled**.
- Optional strict: `THIRAMAI_DISABLE_LEGACY_FALLBACK=true` — no Groq `run_decision_engine` fallback in `api/routes/ai_chat.py`; PolicyEngine exceptions propagate from `services/decision_brain_v2.py`.

## Verify engine

1. Readiness: `curl -sS "$BASE/health/ready" | jq '.checks.policy_engine'`
2. Decision row: `payload->'data'->>'decision_brain_source'` should be `policy_engine` when V2 mapping succeeded (see `api/routes/ai_chat.py` → `_bundle_from_decision_brain_v2`).

## Common causes

| Cause | What to do |
|-------|------------|
| PolicyEngine exception (import, numpy, world model) | Stack trace in web logs; fix deps / config. |
| `_bundle_from_decision_brain_v2` returns `None` | Policy arm not in `_POLICY_ARM_TO_AIDECISION_ACTION` (`api/routes/ai_chat.py`); extend mapping. |
| Strict mode 503 | Expected when Groq fallback is disabled and V2 cannot build a bundle; fix mapping or PolicyEngine. |

## Escalation

If failures persist after config verification and redeploy, treat as P1 for AI decision path and page on-call per `docs/runbooks/README.md`.
