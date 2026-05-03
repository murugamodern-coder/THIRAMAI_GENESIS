# Runbook: Rate limit breaches

**Owner:** Platform on-call  
**Last updated:** 2026-05-01  
**Default severity:** Medium (P2) — can become P1 if legitimate traffic blocked

## Overview

External APIs (broker, LLM, search) or your **edge** return **429** / throttle errors; users see failed actions or retries amplify load.

## Symptoms

- [ ] Logs full of 429, `rate limit`, `retry-after`.
- [ ] Increased latency with successful small requests (queueing).

## Actions

1. Confirm **which dependency** (headers, metrics, vendor dashboard).
2. **Reduce** outbound concurrency: lower worker parallelism, backoff with jitter.
3. **Request** quota increase from vendor if sustained growth is valid.
4. Add **circuit breaker** behavior where the codebase supports it (`core/stability/circuit_breaker`).

## Related

- [API availability](./api-availability.md)  
- [High latency](./high-latency.md)
