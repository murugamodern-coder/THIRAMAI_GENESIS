# Runbook: Cache issues (Redis)

**Owner:** Platform on-call  
**Last updated:** 2026-05-01  
**Default severity:** Medium (P2)

## Overview

**Redis** is down, slow, or returning wrong data. When `REDIS_URL` is set, `/health/ready` includes a `redis` check (`redis_ping_ok` in `api/routes/health.py`). Autonomy halt and some workers rely on Redis.

## Symptoms

- [ ] `/health/ready` shows `redis.ok: false`.
- [ ] Global halt cannot be set or cleared (`503` from `/autonomy/safety/global-halt`).
- [ ] Worker heartbeats missing if `THIRAMAI_HEALTH_EXPECT_WORKERS` is configured.

## Actions

1. From a bastion: `redis-cli -u "$REDIS_URL" PING`.
2. Check **memory**, **eviction**, **replication** lag in provider console.
3. **Restart** Redis primary only per runbook (may lose ephemeral keys — confirm impact).
4. If app misconfig: fix `REDIS_URL`, redeploy.

## Related

- [High latency](./high-latency.md)  
- [Trading halt](./trading-halt.md) if halt semantics break
