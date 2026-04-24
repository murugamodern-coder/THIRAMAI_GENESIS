"""
Result and revenue engine: candidate generator only (no direct execution).
"""

from __future__ import annotations

from typing import Any

from services.value_generation_engine import run_value_generation_cycle


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _safe_text(s: Any, n: int = 220) -> str:
    return str(s or "").strip().replace("\n", " ")[:n]


def _is_irreversible_or_external(text: str) -> bool:
    t = str(text or "").lower()
    blocked = (
        "pay",
        "transfer",
        "wire",
        "delete",
        "drop table",
        "deploy",
        "contract",
        "trade",
        "buy",
        "sell",
        "invoice",
        "order_stock",
        "sell_stock",
        "api call",
        "external",
        "webhook",
        "production change",
    )
    return any(k in t for k in blocked)


def _safe_command_from_item(item: dict[str, Any]) -> str:
    title = _safe_text(item.get("title"), 180)
    steps = [str(x) for x in list(item.get("execution_steps") or [])]
    step = _safe_text(steps[0] if steps else "run one low-risk internal optimization check", 180)
    return (
        "Run a safe internal optimization experiment only (no external mutations, no financial irreversible actions): "
        f"{title}. First action: {step}."
    )[:1200]


def _estimate_roi_signal(*, item: dict[str, Any]) -> dict[str, Any]:
    roi_base = _to_float(item.get("roi_potential"), 0.5)
    feas = _to_float(item.get("execution_feasibility"), 0.5)
    risk = _to_float(item.get("risk"), 0.5)
    realized_roi = (roi_base * 0.60) + (feas * 0.25) - (risk * 0.20)
    realized_roi = max(-1.0, min(2.0, realized_roi))
    revenue_signal = max(0.0, min(1.0, (roi_base * 0.55) + (0.20) - (risk * 0.18)))
    return {
        "estimated_roi_delta": round(realized_roi, 4),
        "revenue_signal_score": round(revenue_signal, 4),
        "roi_basis": {
            "roi_potential": round(roi_base, 4),
            "execution_feasibility": round(feas, 4),
            "risk": round(risk, 4),
        },
    }


def run_result_execution_cycle(
    user_id: int,
    organization_id: int,
    *,
    value_generation: dict[str, Any] | None = None,
    max_actions: int = 2,
) -> dict[str, Any]:
    uid = int(user_id)
    oid = int(organization_id)
    vg = value_generation if isinstance(value_generation, dict) else run_value_generation_cycle(uid, oid, command_hint="result_execution_cycle")
    ranked = [x for x in list(vg.get("priority_ranking") or []) if isinstance(x, dict)]
    if not ranked:
        ranked = []
        for key in ("new_opportunities", "improvements", "research_insights", "strategic_moves"):
            ranked.extend([x for x in list(vg.get(key) or []) if isinstance(x, dict)])

    safe_candidates: list[dict[str, Any]] = []
    for row in ranked:
        if not bool(row.get("safe_to_execute")):
            continue
        if bool(row.get("assist_required")):
            continue
        risk = _to_float(row.get("risk"), 1.0)
        if risk >= 0.70:
            continue
        text_blob = " ".join([_safe_text(row.get("title")), _safe_text(row.get("why")), " ".join([_safe_text(s) for s in list(row.get("execution_steps") or [])])])
        if _is_irreversible_or_external(text_blob):
            continue
        safe_candidates.append(row)
        if len(safe_candidates) >= max(1, min(int(max_actions), 4)):
            break

    execution_candidates: list[dict[str, Any]] = []
    roi_estimates: list[dict[str, Any]] = []
    revenue_signals: list[dict[str, Any]] = []
    for item in safe_candidates:
        command = _safe_command_from_item(item)
        est = _estimate_roi_signal(item=item)
        execution_candidates.append(
            {
                "source": "value_execution",
                "title": _safe_text(item.get("title")),
                "command": command,
                "confidence": _to_float(item.get("execution_feasibility"), 0.6),
                "risk": _to_float(item.get("risk"), 0.3),
                "mission_alignment": _to_float(item.get("mission_alignment"), 0.5),
                "priority_score": _to_float(item.get("priority_score"), 0.5),
                "safe_to_execute": True,
                "assist_required": False,
                "estimated_roi_delta": est["estimated_roi_delta"],
                "revenue_signal_score": est["revenue_signal_score"],
            }
        )
        roi_estimates.append({"title": _safe_text(item.get("title")), **est})
        revenue_signals.append(
            {
                "title": _safe_text(item.get("title")),
                "revenue_signal_score": est["revenue_signal_score"],
                "potential": "high" if float(est["revenue_signal_score"]) >= 0.66 else ("medium" if float(est["revenue_signal_score"]) >= 0.4 else "low"),
            }
        )

    return {
        "execution_candidates": execution_candidates,
        "results": [],
        "roi_estimates": roi_estimates,
        "revenue_signals": revenue_signals,
        "failures": [],
        "selection": {
            "input_ranked_count": len(ranked),
            "safe_candidate_count": len(safe_candidates),
            "max_actions": max(1, min(int(max_actions), 4)),
        },
    }

