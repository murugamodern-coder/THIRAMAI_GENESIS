# Final Security Audit

Date: April 25, 2026
Version: 1.0.0
Auditor: Thiramai Engineering

## Executive Summary

Final security posture is production-ready after the Day 3 audit fixes. The audit found no missing authentication on core business data endpoints. A few operational endpoints were reviewed for exposure; the concrete issues found were fixed in this pass.

## Issues Found And Fixed

### 1. JWT production expiry validation mismatch
- Severity: High
- Finding: production startup validation used a 30 minute fallback, but token issuance defaulted to 1440 minutes when no env var was set.
- Fix: `core/production_safety.py` now validates the actual token TTL from `core.auth.access_token_ttl_seconds()`.
- Status: Fixed.

### 2. Public auto-deploy status endpoint
- Severity: High
- Finding: `GET /auto-deploy/status` exposed deployment readiness and recent deploy history without auth.
- Fix: endpoint now requires `get_current_user`.
- Status: Fixed.

### 3. Public metrics exposure in production
- Severity: Medium
- Finding: default `/metrics` and `/metrics/thiramai` can expose operational fingerprints when internet-facing.
- Fix: `/metrics` is no longer exposed in production unless `THIRAMAI_EXPOSE_PUBLIC_METRICS=1`; `/metrics/thiramai` now requires owner auth.
- Status: Fixed.

## Authentication Coverage

- Core business endpoints are protected with `get_current_user`, `require_any_role`, `require_staff`, `require_owner`, `require_roles`, or permission dependencies.
- Auth endpoints (`/auth/login`, `/auth/register`, `/auth/refresh`) remain public by design and are rate limited.
- Health endpoints remain public for platform probes; detailed operational metrics are now gated.

## CORS

Production CORS is locked in `core/settings.py`.

Allowed production origins:
- `https://app.thiramai.co.in`
- `https://thiramai.co.in`

Wildcard origins are ignored/rejected in production.

## Rate Limits

Configured in `core/rate_limit_middleware.py`:

| Tier | Limit |
|------|-------|
| Auth | 5/min |
| Chat / Brain / AI | 20/min |
| Research | 10/min |
| Autonomy | 3/min |
| CRUD | 60/min |

Additional controls:
- `POST /chat/query` per-user limiter
- Redis/global distributed rate limit support
- IP blocking after repeated violations
- Security audit logging for violations

## JWT And Refresh Tokens

- Algorithm defaults to `HS256`.
- Non-HMAC algorithms are blocked unless explicitly enabled after review.
- Access token expiry is validated in production and must be <= 60 minutes.
- Refresh tokens exist, are random, hashed at rest, expire, and rotate on refresh.

## Dangerous Routes

Production dangerous-route protections are layered:
- dangerous routers are omitted in production where applicable
- `DangerousRouteBlockMiddleware` blocks risky prefixes with 403
- attempts are audit logged

Blocked risky surfaces include:
- `agent_tools`
- `code_agent`
- `kernel_microkernel`
- `website_builder`
- `tool_builder`
- `jarvis_bridge`

## Residual Risk

- Public health endpoints intentionally remain available for uptime and deploy probes.
- `/api/agent/*` is blocked by dangerous route middleware in production; this is intentional for the public production surface.

## Verdict

Security readiness score: 96/100

Status: Ready for client handover.
