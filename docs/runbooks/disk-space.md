# Runbook: Disk space low

**Owner:** Infrastructure on-call  
**Last updated:** 2026-05-01  
**Default severity:** Medium (P2)

## Overview

Local or volume **disk utilization** high on app nodes, DB, or log aggregators risks write failures and corruption.

## Symptoms

- [ ] Host metrics: partition above roughly 85–90% used.
- [ ] Logs: `No space left on device`.

## Actions

1. Identify **volume** (logs, uploads, DB WAL, container layers).
2. **Trim** old logs safely; rotate per policy.
3. Expand volume or **move** data tier; for DB coordinate with DBA.
4. Add **alerting** on free space percentage with lead time.

## Related

- [Data loss](./data-loss.md) if forced shutdown mid-write
