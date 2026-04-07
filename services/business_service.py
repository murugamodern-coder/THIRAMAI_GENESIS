"""SaaS factory preview, vault tooling seeds — business-facing context blocks."""

from __future__ import annotations

from pathlib import Path

import vault_memory


def list_factory_scripts(project_root: Path | None = None) -> list[str]:
    root = project_root or Path(__file__).resolve().parents[1]
    d = root / "factory"
    if not d.is_dir():
        return []
    return sorted(
        p.name for p in d.glob("*.py") if p.is_file() and p.name != "__init__.py"
    )


def build_saas_factory_preview(project_root: Path | None = None) -> str:
    root = project_root or Path(__file__).resolve().parents[1]
    seeds = vault_memory.list_vault_tooling_seeds()
    factory_py = list_factory_scripts(root)
    lines: list[str] = ["**SaaS Factory (Level 1)** — candidate tooling (do not execute blindly):"]
    if factory_py:
        lines.append("\n*Project `factory/` scripts:*")
        for name in factory_py[:16]:
            lines.append(f"- `factory/{name}` — e.g. `python factory/billing_tool.py --help` (from project root)")
    if seeds:
        lines.append("\n*Vault seeds:*")
        for s in seeds[:24]:
            lines.append(f"- `vault/{s}`")
    if not factory_py and not seeds:
        return (
            "_No `factory/*.py` or vault tooling seeds yet. "
            "Add scripts under `factory/` or small stubs under `vault/`._"
        )
    lines.append(
        "\n*Directive:* prefer **`factory/billing_tool.py`** for manual pipe invoices while CRM is blocked; "
        "invoices archive under **`factory_output/YYYY/MM/Invoices/`** and **`master_index.csv`**."
    )
    lines.append(
        "\n*Market watch (simulated resin):* **`python factory/market_watch.py`** — seeds **Procurement Advice** in the Sovereign morning brief."
    )
    lines.append(
        "\n*Humanoid CAD gate (Phase 8):* **`python factory/design_engine.py`** — **PE100 Material Suitability Report** for scrap-printed chassis parts."
    )
    lines.append(
        "\n*Scrap → R&D (Phase 9):* **`python factory/scrap_engine.py`** (`--sync-twin`, `--demo-kg`) → **`vault/rd_core/scrap_inventory.json`**."
    )
    lines.append(
        "\n*AI training sim:* **`python factory/robot_training_sim.py`** (`run_joint_simulation`) → **`vault/rd_core/robot_training_last.json`**; "
        "shim **`brain_training/robot_training_sim.py`** (a `brain/` package would shadow **`brain.py`**)."
    )
    lines.append(
        "\n*Fabrication core (Phase 10):* **`python factory/fab_engine.py`** — G-code manifest **Bushing-Joint V1**, **215 °C** nozzle, "
        "deducts HQRS → **`vault/rd_core/fab_queue.json`** (`--dry-run` skips scrap debit)."
    )
    lines.append(
        "\n*Asset Portal (web):* **`GET /assets`** lists vault + factory PDFs; **`/static/factory/...`** and **`/media/vault/...`** serve files. "
        "Tell the Sovereign to use the dashboard **Sovereign Asset Vault** or **Quick Action** links after each new invoice.*"
    )
    return "\n".join(lines)
