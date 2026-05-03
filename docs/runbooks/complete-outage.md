# Runbook: Complete service outage

**Owner:** Platform on-call  
**Last updated:** 2026-05-01  
**Default severity:** Critical (P0)

## Overview

Customers cannot use the product: load balancer errors, DNS failure, all app instances down, or region-wide incident.

## Symptoms

- [ ] Synthetic checks down; status page red.
- [ ] `/health/live` fails from multiple networks or **all** replicas unhealthy.
- [ ] CDN / WAF blocks; certificate errors; DNS NXDOMAIN.

## Immediate actions

1. Confirm **external** vs **internal-only** (corporate VPN split horizon).
2. Check **provider status** (cloud, CDN, DNS, ISP).
3. If recent deploy: **rollback** front app + API ([TEMPLATE rollback](./TEMPLATE.md#rollback)).
4. If database: **[database-failover](./database-failover.md)**.
5. Open **incident commander** role; freeze non-fix deploys.

## Investigation checklist

| Layer | Check |
| ----- | ----- |
| DNS | `dig +short your.hostname` resolves to expected targets |
| TLS | `curl -vI https://your.hostname` — cert valid, handshake OK |
| Edge | LB target health, WAF rules, rate limits |
| App | Pod/process count, crash loops, OOMKilled |
| DB/Redis | `/health/ready` JSON if any instance reachable |

## Resolution

Restore **ingress to app to dependencies** order; validate with `/health/live` then `/health/ready` then an authenticated UI path.

## Related

- [API availability](./api-availability.md)  
- [High latency](./high-latency.md)
