"""
THIRAMAI Self-Improvement Engine
Learns from: trade outcomes, research accuracy, task completion
Improves: prompt weights, confidence thresholds, strategy params
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional
from pathlib import Path

_log = logging.getLogger("thiramai.self_improvement")

LEARNING_LOG_PATH = Path(os.getenv("THIRAMAI_LEARNING_PATH", "runtime/learning_log.jsonl"))

def record_outcome(
    action_type: str,
    action_id: str,
    predicted: Any,
    actual: Any,
    success: bool,
    metadata: Optional[dict] = None,
) -> dict:
    """Record an action outcome for learning."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action_type": action_type,
        "action_id": action_id,
        "predicted": predicted,
        "actual": actual,
        "success": success,
        "metadata": metadata or {},
    }
    LEARNING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEARNING_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    _log.info("Outcome recorded: %s %s success=%s", action_type, action_id, success)
    return entry

def get_success_rate(action_type: str, days: int = 7) -> dict:
    """Calculate success rate for an action type over recent days."""
    if not LEARNING_LOG_PATH.exists():
        return {"action_type": action_type, "success_rate": 0, "count": 0}
    cutoff = datetime.utcnow() - timedelta(days=days)
    total = 0
    success = 0
    with open(LEARNING_LOG_PATH) as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry["action_type"] != action_type:
                    continue
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts < cutoff:
                    continue
                total += 1
                if entry["success"]:
                    success += 1
            except Exception:
                continue
    return {
        "action_type": action_type,
        "success_rate": (success / total * 100) if total > 0 else 0,
        "total": total,
        "success": success,
        "days": days,
    }

def get_improvement_recommendations() -> list[dict]:
    """Analyze outcomes and recommend improvements."""
    action_types = [
        "options_trade", "equity_trade", "research_query",
        "inventory_reorder", "billing_action"
    ]
    recommendations = []
    for action_type in action_types:
        stats = get_success_rate(action_type)
        if stats["total"] == 0:
            continue
        rate = stats["success_rate"]
        if rate < 50:
            recommendations.append({
                "action_type": action_type,
                "issue": "Low success rate",
                "success_rate": rate,
                "recommendation": f"Review {action_type} logic — only {rate:.1f}% success",
                "priority": "HIGH",
            })
        elif rate < 75:
            recommendations.append({
                "action_type": action_type,
                "issue": "Medium success rate",
                "success_rate": rate,
                "recommendation": f"Optimize {action_type} — {rate:.1f}% success",
                "priority": "MEDIUM",
            })
    return recommendations
