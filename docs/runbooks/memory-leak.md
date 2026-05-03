# Runbook: Memory leak or runaway process growth

**Owner:** Platform on-call  
**Last updated:** 2026-05-01  
**Default severity:** Medium (P2) until OOM — then P1/P0

## Overview

Process **RSS grows** without bound until OOM or sluggish GC. Prometheus gauges `thiramai_memory_usage_mb` and `thiramai_process_uptime_seconds` (see `services/observability/business_metrics.py`) help correlate restarts vs growth.

## Symptoms

- [ ] Steady climb of **memory** panel on `thiramai-overview` dashboard.
- [ ] OOMKilled pods or process restarts with no deploy.
- [ ] Latency rises as swapping or GC pauses increase.

## Investigation

1. Compare memory trend to **deploy** markers and **traffic**.
2. Capture **heap** profile if runtime supported (e.g. py-spy, tracemalloc snapshot in staging only).
3. Check **per-request** leaks (unclosed DB sessions, large in-memory caches).

## Mitigation

- **Restart** instance as temporary relief; watch if leak returns (confirms leak vs traffic).
- **Scale horizontally** to absorb while fixing root cause.
- Reduce **batch sizes** for background jobs if applicable.

## Related

- [High latency](./high-latency.md)
