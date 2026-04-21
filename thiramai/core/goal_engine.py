"""
THIRAMAI sovereign goal engine: autonomous goal generation, prioritization,
and resource-aware selection for the decision loop.
"""

from __future__ import annotations

import json
import time
from typing import Any

from thiramai.config import THIRAMAI_GOAL
from thiramai.integrations.system_metrics import get_system_status

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None


def get_resource_snapshot() -> dict[str, Any]:
    """
    Track host resources and a coarse LLM cost proxy (cycle-relative units, not USD without billing).
    """
    disk = get_system_status()
    snapshot: dict[str, Any] = {
        "timestamp_utc": int(time.time()),
        "disk_free_gb": disk.get("disk_free_gb"),
        "disk_free_ratio": disk.get("disk_free_ratio"),
    }

    if psutil is not None:
        try:
            snapshot["cpu_percent"] = round(psutil.cpu_percent(interval=0.15), 2)
            vm = psutil.virtual_memory()
            snapshot["memory_percent"] = round(vm.percent, 2)
            snapshot["memory_available_gb"] = round(vm.available / (1024**3), 2)
        except Exception as exc:
            snapshot["cpu_percent"] = None
            snapshot["memory_percent"] = None
            snapshot["memory_error"] = str(exc)
    else:
        snapshot["cpu_percent"] = None
        snapshot["memory_percent"] = None
        snapshot["note"] = "psutil not installed; install psutil for CPU/RAM metrics"

    # Cost proxy: bounded abstract units (caller can increment per LLM call).
    snapshot["cost_units_cycle_estimate"] = 1.0
    return snapshot


def prioritize_goals(goals: list[dict[str, Any]], resources: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Order goals: higher priority_score first; under high CPU/memory pressure prefer lower resource_weight.
    """
    resources = resources or {}
    cpu = resources.get("cpu_percent")
    mem = resources.get("memory_percent")
    pressure = 0.0
    if isinstance(cpu, (int, float)):
        pressure += max(0.0, (cpu - 70) / 30)
    if isinstance(mem, (int, float)):
        pressure += max(0.0, (mem - 75) / 25)

    def sort_key(g: dict[str, Any]) -> tuple[float, float]:
        pr = float(g.get("priority_score", 0))
        rw = float(g.get("resource_weight", 5))
        adjusted = pr - pressure * rw
        return (adjusted, -pr)

    ranked = sorted(goals, key=sort_key, reverse=True)
    return ranked


def select_active_goal(goals: list[dict[str, Any]], resources: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """
    Pick the single goal string to execute this cycle, with metadata for logging/memory.
    """
    if not goals:
        return THIRAMAI_GOAL, {"source": "default", "id": "seed"}
    ordered = prioritize_goals(goals, resources)
    top = ordered[0]
    text = str(top.get("title", "")).strip()
    if not text:
        text = str(top.get("description", THIRAMAI_GOAL)).strip() or THIRAMAI_GOAL
    return text, {"source": "goal_engine", "goal_record": top, "queue": ordered}


def generate_goals(context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Produce a candidate goal set from environment, awareness, learning, and optional LLM synthesis.
    Each item: id, title, description, priority_score (0-100), resource_weight (1-10 lower is cheaper).
    """
    ctx = context or {}
    learning = ctx.get("learning") or {}
    awareness = ctx.get("awareness") or {}
    failures = ctx.get("recent_failures") or []
    seed = str(ctx.get("seed_goal", THIRAMAI_GOAL)).strip() or THIRAMAI_GOAL

    goals: list[dict[str, Any]] = [
        {
            "id": "g_seed",
            "title": seed,
            "description": "Primary mission aligned with operator seed and sovereign loop.",
            "priority_score": 55.0,
            "resource_weight": 5.0,
        },
        {
            "id": "g_stability",
            "title": "Stabilize autonomous loop and reduce repeat failures",
            "description": "Tighten diagnostics and validation using recent failure signals.",
            "priority_score": 45.0,
            "resource_weight": 4.0,
        },
        {
            "id": "g_awareness",
            "title": "Reconcile plan with live system awareness",
            "description": "Cross-check repository health, services, and disk before deeper changes.",
            "priority_score": 40.0,
            "resource_weight": 3.0,
        },
    ]

    risks = awareness.get("risks") if isinstance(awareness, dict) else []
    if isinstance(risks, list) and risks:
        goals.append(
            {
                "id": "g_risk",
                "title": "Mitigate elevated operational risk signals",
                "description": f"Address risks: {', '.join(str(r) for r in risks[:6])}",
                "priority_score": 70.0,
                "resource_weight": 6.0,
            }
        )

    if failures:
        goals.append(
            {
                "id": "g_recovery",
                "title": "Recover from recent execution failures",
                "description": "Prioritize remediation paths suggested by the latest failure payloads.",
                "priority_score": 65.0,
                "resource_weight": 5.0,
            }
        )

    learned = learning.get("learned_rules") if isinstance(learning, dict) else []
    if learned:
        goals.append(
            {
                "id": "g_learned",
                "title": "Apply learned constraints to next actions",
                "description": "Honor learned rules and success patterns from memory.",
                "priority_score": 50.0,
                "resource_weight": 4.0,
            }
        )

    try:
        from thiramai.integrations.llm_clients import multi_llm

        prompt = (
            "You are a sovereign autonomous planner. Given context JSON, emit STRICT JSON only: "
            '{"goals":[{"id":"string","title":"string","description":"string",'
            '"priority_score":0-100,"resource_weight":1-10}]}\n'
            "Return 3-6 concise goals; resource_weight lower means cheaper/safer for overloaded hosts.\n"
            f"CONTEXT:\n{json.dumps(ctx, ensure_ascii=True)[:14000]}\n"
        )
        raw = multi_llm(prompt)
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            extra = parsed.get("goals")
            if isinstance(extra, list):
                for item in extra:
                    if isinstance(item, dict) and item.get("title"):
                        goals.append(
                            {
                                "id": str(item.get("id", f"llm_{len(goals)}")),
                                "title": str(item.get("title", "")).strip(),
                                "description": str(item.get("description", "")).strip(),
                                "priority_score": float(item.get("priority_score", 50)),
                                "resource_weight": float(item.get("resource_weight", 5)),
                            }
                        )
    except Exception:
        pass

    # Deduplicate by title
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for g in goals:
        key = g["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(g)
    return unique
