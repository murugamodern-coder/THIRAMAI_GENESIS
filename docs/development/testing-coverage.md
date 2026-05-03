# Test coverage standards

## Philosophy

Not every module needs the same bar:

- **Critical paths** (money movement, security, secrets, core DB): **enforced in CI** via `scripts/check_critical_coverage.py`.
- **General business logic**: 75%+ recommended.
- **Utilities**: ~70% often acceptable.
- **Presentation-only code**: no global gate.

Thresholds are **selective** (not 100% repo-wide).

## Critical paths

CI loads `coverage.json` from pytest-cov and fails if any listed path is missing or below its minimum. Authoritative list:

`scripts/check_critical_coverage.py` → `CRITICAL_PATHS`

**Baselines:** Numeric `min_coverage` values track the current suite so CI stays green while this rolls out. Tighten toward **85–90%** on money-movement, auth, and secrets as you add tests. Modules that already clear a high bar (e.g. `portfolio_risk_engine`, `walk_forward`, `broker_stops`) keep **85–90%** gates today.

| Area | Examples | Gate today |
|------|----------|------------|
| Quant / trading | `services/quant/` | Baseline % in script; raise toward 85% |
| Risk / stops / walk-forward | named under `services/quant/` | **85–90%** where passing |
| Execution engine | `services/execution_decision_engine.py` | Low floor until tests exist; **target 90%** |
| Trading-related API | `api/routes/stock_assistant.py`, `api/routes/execute.py` | Baseline; raise toward **85%** |
| Auth / crypto | `core/auth.py`, `api/routes/auth.py` | Baseline; raise toward **85%** |
| Secrets | `core/secrets_manager.py` | Baseline; raise toward **90%** |
| DB factory | `core/database.py` | Baseline; raise toward **80%** |
| Decision stack | `services/decision_brain_v2.py`, `services/decision_router.py` | Baseline / **75%** |

## Running coverage locally

From the repo root:

```bash
pip install -r requirements.txt
pytest tests/ \
  --cov=core --cov=services --cov=api --cov=workers \
  --cov-report=term-missing:skip-covered \
  --cov-report=html \
  --cov-report=json \
  --cov-branch
python scripts/check_critical_coverage.py
```

HTML report: `htmlcov/index.html`

Trend snippet (optional, appends `coverage-trends.json`):

```bash
python scripts/track_coverage_trends.py
```

## CI behavior

Workflow: `.github/workflows/test-coverage.yml`

1. Full test run with branch coverage and `.coveragerc` settings.
2. **Critical path gate** (`check_critical_coverage.py`) — must exit 0.
3. **Codecov** upload (`coverage.xml`) — optional token for private repos; `fail_ci_if_error: false` so uploads never block merges.
4. **Artifacts**: HTML report + `coverage.json` + trend file.
5. **PR comment** (`py-cov-action/python-coverage-comment-action`) — best-effort (`continue-on-error: true`).

Main **CI** workflow (`.github/workflows/ci.yml`) remains a fast path without coverage; use the coverage workflow for gates and reports.

## Excluding lines

Prefer `# pragma: no cover` only for unreachable deployment guards. Patterns in `.coveragerc` `exclude_lines` cover common boilerplate (`TYPE_CHECKING`, `raise NotImplementedError`, etc.).

## Anti-patterns

- **No** tests that only call code with no assertions just to raise coverage.
- **No** asserting private implementation details; test observable behavior.
- **Yes** small pure functions for money/risk math — easy to hit high coverage meaningfully.
