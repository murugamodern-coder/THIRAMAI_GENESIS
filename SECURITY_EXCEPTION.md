# THIRAMAI Security Exceptions and Mitigations

Date: 2026-04-24
Owner: Security Engineering / SRE
Scope: Final enterprise-readiness blocker handling for dependency advisories.

## 1) cryptography advisory exception (temporary, controlled)

- Package: `cryptography`
- Runtime pin: `cryptography==46.0.5`
- Why not auto-upgrade right now:
  - Direct upgrades in this environment introduced runtime incompatibility in JWT/auth code paths tied to `python-jose[cryptography]`.
  - The production risk of auth-path breakage is higher than the residual risk after compensating controls.

### Risk explanation

- Potential risk: known vulnerability in upstream `cryptography` release line.
- Impact area in this system is reduced because THIRAMAI uses symmetric JWT (`HS*`) and does not rely on asymmetric certificate parsing for normal auth flows.
- Residual risk is accepted only with explicit controls below.

### Mitigation controls implemented

1. Version pinning
   - `requirements-base.txt` pins `cryptography==46.0.5` to avoid accidental drift.
2. Usage isolation
   - `core/auth.py` enforces symmetric JWT by default.
   - Asymmetric JWT algorithms are blocked unless explicitly enabled with `THIRAMAI_ALLOW_ASYMMETRIC_JWT=1` and security review.
3. Runtime validation
   - Startup checks now execute JWT issue/decode roundtrip via `core.auth.runtime_validate_auth_crypto()`.
   - If crypto wiring is broken, startup checks surface failure (`jwt_crypto_runtime`) immediately.
4. Operational guardrails
   - Keep API `/health/ready` and auth smoke checks in deployment validation.
   - Re-run `pip-audit` on each release pipeline.

### Exit criteria for removing exception

- Upgrade to a patched `cryptography` version that passes:
  - auth unit tests,
  - startup runtime validation,
  - production smoke + chaos validation.
- Then remove this exception entry and update dependency pin.

## 2) pip advisory classification

- Package: `pip`
- Classification: non-runtime / build tooling
- Justification:
  - `pip` is not imported by THIRAMAI application runtime.
  - Production request handling path does not execute `pip`.
  - Advisory does not expose serving-plane behavior unless package installation is performed in a compromised operational workflow.

### Mitigation for pip advisory

- Restrict package installation to controlled CI/build stages.
- Use immutable production images and no live-install on running app containers.
- Track `pip` updates in base image maintenance cadence.

## Approval

This exception is a temporary controlled risk decision pending validated compatibility with newer `cryptography` releases.
