"""
Real-time event intelligence:
- monitor external/system signals
- detect anomalies
- emit actionable triggers
"""

from __future__ import annotations

from typing import Any

from services.autonomy_safety_layer import safety_monitoring_summary
from services.predictive_engine import prediction_summary
from services.world_model_engine import get_world_model


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def detect_realtime_triggers(
    *,
    user_id: int,
    organization_id: int,
) -> dict[str, Any]:
    _ = int(organization_id)
    pred = prediction_summary(int(user_id))
    world = get_world_model(int(user_id))
    safe = safety_monitoring_summary(int(user_id), hours=24)

    triggers: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []

    risk = pred.get("predicted_risk") if isinstance(pred.get("predicted_risk"), dict) else {}
    if str(risk.get("risk_level") or "") == "high" or _safe_float(risk.get("probability"), 0.0) >= 0.72:
        triggers.append(
            {
                "type": "risk_spike",
                "severity": "high",
                "reason": f"predicted_risk={risk.get('risk_level')} prob={risk.get('probability')}",
            }
        )
        anomalies.append({"kind": "risk_anomaly", "signal": risk})

    opp = pred.get("opportunity_success") if isinstance(pred.get("opportunity_success"), dict) else {}
    trend = pred.get("profit_trend") if isinstance(pred.get("profit_trend"), dict) else {}
    if _safe_float(opp.get("success_probability"), 0.0) >= 0.78 and str(trend.get("trend") or "") == "up":
        triggers.append(
            {
                "type": "opportunity_spike",
                "severity": "medium",
                "reason": f"opp_success={opp.get('success_probability')} trend={trend.get('trend')}",
            }
        )

    market = world.get("market_behavior") if isinstance(world.get("market_behavior"), dict) else {}
    regime = str(market.get("regime") or "balanced")
    drift = str(((world.get("risk_patterns") or {}) if isinstance(world.get("risk_patterns"), dict) else {}).get("drift") or "stable")
    if regime in {"defensive", "expansion"} and drift in {"degrading", "improving"}:
        triggers.append(
            {
                "type": "environment_shift",
                "severity": "medium",
                "reason": f"regime={regime} drift={drift}",
            }
        )

    if bool(safe.get("anomaly_suspected")):
        anomalies.append({"kind": "execution_anomaly", "signal": safe})
        if _safe_float(safe.get("failure_rate"), 0.0) >= 0.35:
            triggers.append(
                {
                    "type": "risk_spike",
                    "severity": "high",
                    "reason": f"execution_failure_rate={safe.get('failure_rate')}",
                }
            )

    # de-duplicate by type, keep highest severity first
    sev_rank = {"high": 3, "medium": 2, "low": 1}
    dedup: dict[str, dict[str, Any]] = {}
    for t in triggers:
        tt = str(t.get("type") or "")
        if not tt:
            continue
        cur = dedup.get(tt)
        if cur is None or sev_rank.get(str(t.get("severity") or "low"), 1) > sev_rank.get(str(cur.get("severity") or "low"), 1):
            dedup[tt] = t
    trig_out = list(dedup.values())
    trig_out.sort(key=lambda x: sev_rank.get(str(x.get("severity") or "low"), 1), reverse=True)

    return {
        "ok": True,
        "triggers": trig_out,
        "anomalies": anomalies[:20],
        "signals": {
            "prediction_summary": pred,
            "world_model": world,
            "safety_monitoring": safe,
        },
    }
