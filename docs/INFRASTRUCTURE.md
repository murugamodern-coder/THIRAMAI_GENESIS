# Production infrastructure (Thiramai)

This document describes the **docker-compose.production.yml** stack: services, ports, resource limits, and how to scale safely.

## Architecture overview

| Service          | Role |
|------------------|------|
| **db**           | PostgreSQL 16 (application data, optional job queue when `THIRAMAI_JOB_QUEUE=db`) |
| **redis**        | Redis 7 (caching / broker patterns; tune `REDIS_URL` in `.env.production`) |
| **web**          | FastAPI behind Gunicorn + Uvicorn workers (HTTP API, health endpoints) |
| **worker-jobs**  | Background job processor (`python -m workers.run_worker`) |
| **worker-alerts**| Scheduled retail / stock alerts (`python -m workers.alert_system`) |

All application images are built from the repository **Dockerfile** (multi-stage: Python runtime + optional Command Center frontend).

## Ports

| Exposure | Service | Notes |
|----------|---------|--------|
| `127.0.0.1:${WEB_PORT:-8000}:8000` | **web** | API only bound to loopback on the host; put Nginx/Caddy/ALB in front for public HTTPS. |
| Internal only | **db** | Postgres default `5432` (not published in production compose). |
| Internal only | **redis** | Redis `6379` (not published). |

Workers do not expose ports.

## Resource limits and logging

Compose **`deploy.resources`** and **`logging`** apply when using **Docker Compose v2.23+** (Linux with cgroups). On some platforms, Swarm-specific features were ignored historically; verify with `docker stats` after `up -d`.

### `db` (PostgreSQL)

- **Limits:** 1.0 CPU, 512 MiB RAM  
- **Reservations:** 0.25 CPU, 256 MiB RAM  
- **Logs:** `json-file`, max 10 MiB × 3 files  

Tune Postgres memory (`shared_buffers`, etc.) only if you raise the container memory limit.

### `redis`

- **Limits:** 0.5 CPU, 300 MiB RAM (aligns with `maxmemory 256mb` in command + overhead)  
- **Reservations:** 0.1 CPU, 256 MiB RAM  
- **Logs:** `json-file`, max 10 MiB × 3 files  

### `web` (API)

- **Limits:** 2.0 CPU, 1 GiB RAM  
- **Reservations:** 0.5 CPU, 512 MiB RAM  
- **Logs:** `json-file`, max 50 MiB × 5 files  

**Gunicorn workers:** controlled by `GUNICORN_WORKERS` (see `.env.production.example`). Rule of thumb: start with `(2 × CPU cores) + 1` for sync-bound work; for I/O-bound APIs, 4–8 is common. Each worker is a process; do not exceed RAM available to the container.

### `worker-jobs`

- **Limits:** 1.0 CPU, 512 MiB RAM  
- **Reservations:** 0.25 CPU, 256 MiB RAM  
- **Logs:** `json-file`, max 20 MiB × 3 files  

Poll interval: `THIRAMAI_WORKER_POLL_SEC` (default `2`).

### `worker-alerts`

- **Limits:** 0.5 CPU, 256 MiB RAM  
- **Reservations:** 0.1 CPU, 128 MiB RAM  
- **Logs:** `json-file`, max 20 MiB × 3 files  

Schedule: `THIRAMAI_ALERT_INTERVAL_MINUTES` (default `15`).

## Restart policy

All services use **`restart: unless-stopped`**: containers restart after daemon reboot or crash, unless explicitly stopped.

## Scaling guidance

- **Horizontal API scaling:** run multiple **web** replicas behind a load balancer only after sessions and job handling are verified stateless or sticky sessions are configured; database connection pools must be sized per replica.  
- **Vertical scaling:** increase **`deploy.resources.limits`** before raising `GUNICORN_WORKERS` or Postgres memory.  
- **Workers:** scale **worker-jobs** replicas if the queue backs up; keep **worker-alerts** at one replica unless you partition alert domains to avoid duplicate notifications.

## Related documentation

- Environment template: **`.env.production.example`**  
- Supply chain / dependencies: **`docs/SUPPLY_CHAIN_SECURITY.md`**  
- Deploy workflow: **`.github/workflows/deploy.yml`** and **`.github/DEPLOY_SETUP.md`**
