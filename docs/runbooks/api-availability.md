# Runbook: API availability / error budget burn

## Symptoms

- Alerts: `APIAvailabilityFastBurn`, `APIAvailabilitySlowBurn`, or rising 5xx ratio.
- Grafana: `slo:api_availability:burn_rate:*` elevated; `thiramai_requests_total{status=~"5.."}` up.

## Immediate checks (first 5 minutes)

1. Confirm scope: single region/pod vs global (load balancer, ingress, app replicas).
2. Recent deploy or config change — consider rollback if correlated.
3. Open `/health/ready` and `/health/live` on affected instances; read dependency checks.
4. Slice `thiramai_requests_total` by `handler` / `method` / `status` if labels exist.

## Common causes

- Dependency outage (database, Redis, broker, LLM provider timeouts surfacing as 5xx).
- Saturation (CPU, pool exhaustion — correlate with `DatabasePoolExhaustion*` alerts).
- Bad release (exceptions in new code paths).

## Mitigation

- Scale replicas or roll back release per your playbook.
- Enable **incident / degraded** mode if the product supports reducing background load.
- If DB-bound, follow `docs/runbooks/db-pool-exhaustion.md`.

## After resolution

- Document timeline and root cause; update `docs/INCIDENT_PLAYBOOK.md` if gaps found.
- If budget was heavily consumed, schedule reliability work before aggressive feature work.

## Related

- [Runbook template](./TEMPLATE.md) and [index](./README.md)
- Grafana: `thiramai-slo-overview`
