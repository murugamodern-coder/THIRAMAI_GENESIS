"""Action simulation engine: evaluate candidate outcomes before execution."""

from __future__ import annotations

from typing import Any

from services.feedback_engine import calculate_prediction_accuracy
from services.predictive_engine import prediction_summary
from services.world_model_engine import get_world_model


def _risk_factor(level: str) -> float:
    lv = str(level or "medium").lower()
    if lv == "low":
        return 0.25
    if lv == "high":
        return 0.85
    return 0.5


def simulate_action_paths(user_id: int, action_context: dict[str, Any]) -> dict[str, Any]:
    pred = prediction_summary(int(user_id))
    world = get_world_model(int(user_id))
    fb = calculate_prediction_accuracy(int(user_id), limit=220)
    base_profit = float((action_context or {}).get("expected_profit") or 1000.0)
    confidence = float(pred.get("confidence_score") or 0.5)
    risk_level = str(((pred.get("predicted_risk") or {}).get("risk_level")) or "medium")
    rf = _risk_factor(risk_level)
    trust = float(fb.get("system_trust_score") or 50.0) / 100.0
    # Simple multi-path scenario simulation.
    paths = [
        {
            "path": "conservative",
            "estimated_profit": round(base_profit * (0.5 + (trust * 0.2)), 2),
            "estimated_risk": round(max(0.05, rf * 0.6), 3),
            "success_probability": round(min(0.95, confidence * 0.9 + trust * 0.1), 3),
        },
        {
            "path": "balanced",
            "estimated_profit": round(base_profit * (0.8 + (confidence * 0.2)), 2),
            "estimated_risk": round(max(0.08, rf * 0.85), 3),
            "success_probability": round(min(0.95, confidence * 0.95 + trust * 0.05), 3),
        },
        {
            "path": "aggressive",
            "estimated_profit": round(base_profit * (1.2 + (confidence * 0.25)), 2),
            "estimated_risk": round(min(0.99, rf * 1.2 + 0.1), 3),
            "success_probability": round(max(0.1, min(0.9, confidence * 0.85 - (rf * 0.15))), 3),
        },
    ]
    for p in paths:
        score = (float(p["estimated_profit"]) * float(p["success_probability"])) - (float(p["estimated_risk"]) * max(base_profit, 1.0) * 0.5)
        p["path_score"] = round(score, 2)
    paths.sort(key=lambda x: float(x.get("path_score") or 0), reverse=True)
    return {
        "ok": True,
        "world_context": world,
        "paths": paths,
        "recommended_path": paths[0] if paths else None,
    }


def choose_best_simulated_path(user_id: int, action_context: dict[str, Any]) -> dict[str, Any]:
    sim = simulate_action_paths(int(user_id), action_context or {})
    rec = sim.get("recommended_path") or {}
    return {"ok": True, "simulation": sim, "chosen_path": rec}
