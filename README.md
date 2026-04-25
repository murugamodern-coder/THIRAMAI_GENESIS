# THIRAMAI

THIRAMAI is an autonomous planning and execution framework with policy enforcement, local knowledge retrieval, HITL approvals, and telemetry dashboards for industrial and agricultural workflows.

## Core Use Cases

- Agro-industrial planning (for example: jaggery plant feasibility, drip irrigation decisions, biomass energy usage).
- Business operations automation (for example: maraseku oil workflows, inventory-oriented task orchestration).
- Safe autonomous execution with policy checks, review loops, and audit trails.

## Feature Status

| Feature | Status | Expected |
|---------|--------|----------|
| Command Center | ✅ Live | - |
| Control Center | ✅ Live | - |
| Inventory | ✅ Live | - |
| Billing | ✅ Live | - |
| Production | ✅ Live | - |
| Personal OS | ✅ Live | - |
| Stock Watchlist | ✅ Live | - |
| Research | ✅ Live | - |
| Analytics | 🔜 Coming | Q2 2026 |
| GST Filing | 🔜 Coming | Q3 2026 |
| Payroll | 🔜 Coming | Q3 2026 |
| Reports | 🔜 Coming | Q2 2026 |
| Settings | 🔜 Coming | Q2 2026 |

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install package:
   - `pip install -e .`
3. Configure environment variables in `.env` (at minimum set runtime mode and relevant API keys if you need live LLM).

## CLI Commands

- `thiramai run "your goal"`  
  Runs the full autonomous loop (Planner -> Agent execution -> Reviewer -> Retry/Replan).

- `thiramai dashboard`  
  Launches the Streamlit monitoring interface with HITL controls.

- `thiramai doctor`  
  Validates Docker/runtime dependencies and key configuration health.

## Runtime Directories

These directories are auto-created by CLI startup:

- `logs/` for audit logs and telemetry artifacts.
- `knowledge/` for local domain files (`.json`, `.md`).
- `runtime/` for HITL flags and transient control files.

## Knowledge Mapping Inputs

Place domain files under `knowledge/`:

- `land_profile.json`
- `agro_industrial_basics.md`
- `business_operations.md`

The Researcher agent checks local knowledge first and only falls back to web search when local relevance is insufficient.

## HITL High-Risk Approvals

High-risk commands (`risk_level=high`) require manual approval before execution.

- Approve: create `runtime/hitl/approve.flag` (or use dashboard button).
- Reject: create `runtime/hitl/reject.flag` (or use dashboard button).

## Dashboard Export

From Streamlit UI, you can export a generated DPR report as Markdown and optionally PDF (if `reportlab` is installed).
