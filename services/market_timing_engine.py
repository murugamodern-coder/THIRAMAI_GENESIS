"""Market timing: trends, momentum, entry/exit, confidence — uses predictive + feedback engines."""

from __future__ import annotations

import math
import statistics
from typing import Any

from services.feedback_engine import adjust_model_weights, calculate_prediction_accuracy
from services.predictive_engine import (
    detect_market_shift,
    forecast_profit_trend,
    predict_opportunity_success,
    predict_risk_spike,
    recent_profit_value_series,
)


def _trend_dir(delta_ratio: float, lo: float = 0.012, hi: float = 0.012) -> str:
    if delta_ratio > lo:
        return "up"
    if delta_ratio < -hi:
        return "down"
    return "flat"


def _moving_avg(ys: list[float], n: int) -> float:
    if not ys:
        return 0.0
    w = min(max(1, n), len(ys))
    return float(sum(ys[-w:]) / w)


def _linear_slope(ys: list[float]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    y_bar = sum(ys) / n
    x = list(range(n))
    x_bar = (n - 1) / 2.0
    num = sum((x[i] - x_bar) * (ys[i] - y_bar) for i in range(n))
    den = sum((x[i] - x_bar) ** 2 for i in range(n)) or 1.0
    return float(num / den)


def _series_to_chronological(newest_first: list[float]) -> list[float]:
    if not newest_first:
        return []
    return list(reversed(newest_first))


def detect_trends_from_values(values: list[float]) -> dict[str, Any]:
    """Chronology: `values[0]` = most recent (same as profit log order in predictive engine)."""
    ch = _series_to_chronological(values)
    n = len(ch)
    if n < 2:
        return {
            "short_trend": "unknown",
            "long_trend": "unknown",
            "alignment": "unknown",
            "ma_short": None,
            "ma_long": None,
            "sample_size": n,
        }
    m_short = _moving_avg(ch, 5) if n >= 5 else _moving_avg(ch, n)
    m_long = _moving_avg(ch, 20) if n >= 20 else _moving_avg(ch, n)
    if n >= 10:
        recent5 = _moving_avg(ch[-5:], 5)
        prev5 = _moving_avg(ch[-10:-5], 5)
        short = _trend_dir((recent5 - prev5) / max(abs(prev5) + 1.0, 1.0))
    elif n >= 6:
        recent3 = _moving_avg(ch[-3:], 3)
        prev3 = _moving_avg(ch[-6:-3], 3)
        short = _trend_dir((recent3 - prev3) / max(abs(prev3) + 1.0, 1.0))
    else:
        short = "up" if ch[-1] > ch[0] else "down" if ch[-1] < ch[0] else "flat"
    if n >= 24:
        late = _moving_avg(ch[-20:], 20)
        orig = _moving_avg(ch[:20], 20) if n >= 40 else _moving_avg(ch[: n // 2], n // 2)
        long_d = (late - orig) / max(abs(orig) + 1.0, 1.0)
    elif n >= 8:
        m = n // 2
        late = _moving_avg(ch[m:], min(5, n - m)) if m < n else m_long
        orig = _moving_avg(ch[:m], min(5, m)) if m else 0.0
        long_d = (late - orig) / max(abs(orig) + 1.0, 1.0)
    else:
        long_d = (m_short - m_long) / max(abs(m_long) + 1.0, 1.0)
    long_ = _trend_dir(float(long_d), lo=0.02, hi=0.02)
    a_short = _linear_slope(ch[-min(5, n) :])
    a_long = _linear_slope(ch[max(0, n - 20) :]) if n >= 4 else a_short
    st_set = {short, long_}
    if short == long_ and short in ("up", "down"):
        align = "aligned"
    elif "flat" in (short, long_):
        align = "transition"
    else:
        align = "divergent"
    return {
        "short_trend": short,
        "long_trend": long_,
        "alignment": align,
        "ma_short": round(m_short, 4),
        "ma_long": round(m_long, 4),
        "slope_short": round(a_short, 8),
        "slope_long": round(a_long, 8),
        "sample_size": n,
    }


def momentum_score_from_values(values: list[float], *, lookback: int = 5) -> dict[str, Any]:
    ch = _series_to_chronological(values)
    n = len(ch)
    if n < 2:
        return {"momentum_0_100": 50.0, "label": "neutral", "strength": 0.0}
    tail = ch[-min(lookback, n) :]
    s = _linear_slope(tail)
    scale = max(1.0, statistics.pstdev(ch) if n >= 2 and len(set(ch)) > 1 else (abs(ch[-1]) * 0.1 + 1.0))
    z = s / scale
    raw = math.tanh(z * 1.2)
    m = 50.0 + 50.0 * raw
    m = max(0.0, min(100.0, m))
    if m >= 62.0:
        label = "bullish"
    elif m <= 38.0:
        label = "bearish"
    else:
        label = "neutral"
    return {
        "momentum_0_100": round(m, 2),
        "label": label,
        "strength": round(float(abs(raw)), 3),
    }


def _risk_weight(r: dict[str, Any]) -> float:
    level = str(r.get("risk_level") or "medium")
    p = float(r.get("probability") or 0.5)
    w = 0.55 if level == "high" else 0.78 if level == "medium" else 0.92
    return float(max(0.2, w * (1.0 - min(0.35, p * 0.2))))


def _trust_factor(acc: dict[str, Any], weights: dict[str, Any]) -> float:
    tr = float(acc.get("system_trust_score") or 50.0) / 100.0
    cal = float(acc.get("confidence_calibration") or 0.5)
    tm = 1.0
    t = str(acc.get("trend") or "stable")
    if t == "improving":
        tm = 1.05
    elif t == "degrading":
        tm = 0.9
    cw = float(weights.get("confidence_weight") or 1.0)
    base = 0.35 * tr + 0.3 * min(1.0, cal + 0.1) + 0.2 * min(1.0, cw) + 0.15
    return float(max(0.1, min(1.1, base * tm)))


def _compose_timing_confidence(
    *,
    predictive_conf: float,
    momentum: float,
    acc: dict[str, Any],
    weights: dict[str, Any],
    sample_size: int,
) -> dict[str, Any]:
    w_trust = _trust_factor(acc, weights)
    momf = 1.0 - abs(50.0 - momentum) / 100.0
    base = float(0.45 * min(0.99, max(0.1, predictive_conf)) + 0.25 * momf + 0.3 * w_trust)
    if sample_size < 4:
        base *= 0.75
    elif sample_size < 8:
        base *= 0.9
    score = max(0.05, min(0.99, base))
    label = "high" if score >= 0.7 else "medium" if score >= 0.45 else "low"
    return {
        "timing_confidence_0_1": round(score, 3),
        "label": label,
        "inputs": {
            "predictive_confidence": round(float(predictive_conf), 3),
            "momentum_fitness_momf": round(momf, 3),
            "feedback_trust_blend": round(w_trust, 3),
            "series_sample_size": int(sample_size),
        },
    }


def entry_exit_signals(
    trends: dict[str, Any],
    momentum: dict[str, Any],
    pred_trend: dict[str, Any],
    risk: dict[str, Any],
    shift: dict[str, Any],
) -> dict[str, Any]:
    m = float(momentum.get("momentum_0_100") or 50.0)
    st = str(trends.get("short_trend") or "flat")
    lt = str(trends.get("long_trend") or "flat")
    pt = str(pred_trend.get("trend") or "flat")
    r_level = str(risk.get("risk_level") or "medium")
    sig = str(shift.get("signal") or "no_data")
    defensive = "defensive_shift" in sig
    al = str(trends.get("alignment") or "")

    entry = 0.0
    if st == "up" and m >= 52.0:
        entry += 0.28
    if lt in ("up", "flat") and m >= 48.0 and not defensive:
        entry += 0.2
    if al == "aligned" and m >= 50.0 and r_level != "high":
        entry += 0.2
    if pt == "up" and m >= 50.0 and r_level != "high":
        entry += 0.18
    if r_level == "high" or (st == "down" and m < 50.0):
        entry -= 0.35
    if defensive and m < 50.0:
        entry -= 0.2
    entry = max(0.0, min(1.0, entry + 0.0))

    exit_ = 0.0
    if r_level == "high" or (st == "down" and m <= 42.0):
        exit_ += 0.45
    if lt == "down" and m <= 45.0:
        exit_ += 0.25
    if (defensive and m < 45.0) or (m <= 32.0 and st == "down"):
        exit_ += 0.25
    if m >= 55.0 and st in ("up", "flat") and r_level == "low":
        exit_ = max(0.0, exit_ - 0.2)
    exit_ = max(0.0, min(1.0, exit_))

    if entry < 0.2 or r_level == "high":
        entry_lbl = "no_entry" if (entry < 0.1 or r_level == "high") and m < 55.0 else "wait"
    elif entry >= 0.55 and r_level in ("low", "medium") and m >= 48.0 and st != "down":
        entry_lbl = "favorable"
    elif entry >= 0.3:
        entry_lbl = "cautious_enter"
    else:
        entry_lbl = "wait"

    if exit_ >= 0.55:
        ex_lbl = "exit"
    elif exit_ >= 0.35:
        ex_lbl = "reduce"
    else:
        ex_lbl = "hold"

    return {
        "entry": entry_lbl,
        "exit": ex_lbl,
        "entry_strength_0_1": round(float(entry), 3),
        "exit_strength_0_1": round(float(exit_), 3),
        "reasons": {
            "short_trend": st,
            "long_trend": lt,
            "profit_forecast_trend": pt,
            "risk_level": r_level,
            "shift_signal": sig,
            "trend_alignment": al,
        },
    }


def market_timing_pack(
    user_id: int,
    *,
    values: list[float] | None = None,
) -> dict[str, Any]:
    series = list(values) if values is not None and len(values) > 0 else recent_profit_value_series(int(user_id), hours=120)
    pred_t = forecast_profit_trend(int(user_id))
    risk = predict_risk_spike(int(user_id))
    shift = detect_market_shift(int(user_id))
    opp = predict_opportunity_success(int(user_id), None)
    if not series:
        trends = {
            "short_trend": "unknown",
            "long_trend": "unknown",
            "alignment": "unknown",
            "sample_size": 0,
        }
        mom = {"momentum_0_100": 50.0, "label": "neutral", "strength": 0.0}
    else:
        trends = detect_trends_from_values(series)
        mom = momentum_score_from_values(series)
    acc = calculate_prediction_accuracy(int(user_id), limit=200)
    weights = adjust_model_weights(int(user_id))
    pt_conf = (float(pred_t.get("confidence") or 0.5) + float(opp.get("confidence") or 0.5)) / 2.0
    pt_conf = min(0.99, max(0.05, pt_conf * float(weights.get("confidence_weight") or 1.0)))
    w_risk = _risk_weight(risk)
    pred_blend = (pt_conf * 0.6 + w_risk * 0.4) * 0.85
    tconf = _compose_timing_confidence(
        predictive_conf=pred_blend,
        momentum=float(mom.get("momentum_0_100") or 50.0),
        acc=acc,
        weights=weights,
        sample_size=len(series),
    )
    signals = entry_exit_signals(
        trends,
        mom,
        pred_t,
        risk,
        shift,
    )
    if not series:
        signals = {
            **signals,
            "entry": "wait",
            "exit": "hold",
            "note": "No recent profit series; signals rely on portfolio/opportunity heuristics only.",
        }
    return {
        "ok": True,
        "trends": trends,
        "momentum": mom,
        "signals": signals,
        "timing_confidence": tconf,
        "predictive": {
            "profit_trend": pred_t,
            "risk_spike": risk,
            "market_shift": shift,
            "opportunity_success": opp,
        },
        "feedback": _feedback_block(acc, weights),
    }


def _feedback_block(acc: dict[str, Any], weights: dict[str, Any]) -> dict[str, Any]:
    return {
        "accuracy": {k: acc.get(k) for k in ("sample_size", "accuracy_pct", "prediction_error_pct", "trend", "system_trust_score", "confidence_calibration", "per_strategy_accuracy") if k in acc},
        "weight_adjustment": {k: weights.get(k) for k in ("confidence_weight", "mode", "reason", "allocation_bias") if k in weights},
    }


def timing_from_custom_series(
    user_id: int,
    values: list[float],
    *,
    oldest_first: bool = False,
) -> dict[str, Any]:
    """Analyse a caller-supplied series (e.g. prices) with the same layer as `market_timing_pack`."""
    v = [float(x) for x in values if x is not None]
    if oldest_first and v:
        v = list(reversed(v))
    if not v:
        return {"ok": False, "error": "No numeric values", "trends": None, "momentum": None}
    trends = detect_trends_from_values(v)
    mom = momentum_score_from_values(v)
    acc = calculate_prediction_accuracy(int(user_id), limit=200)
    weights = adjust_model_weights(int(user_id))
    pred_t = forecast_profit_trend(int(user_id))
    risk = predict_risk_spike(int(user_id))
    shift = detect_market_shift(int(user_id))
    opp = predict_opportunity_success(int(user_id), None)
    pt_conf = (float(pred_t.get("confidence") or 0.5) + float(opp.get("confidence") or 0.5)) / 2.0
    pt_conf = min(0.99, max(0.05, pt_conf * float(weights.get("confidence_weight") or 1.0)))
    w_risk = _risk_weight(risk)
    pred_blend = (pt_conf * 0.6 + w_risk * 0.4) * 0.85
    tconf = _compose_timing_confidence(
        predictive_conf=pred_blend,
        momentum=float(mom.get("momentum_0_100") or 50.0),
        acc=acc,
        weights=weights,
        sample_size=len(v),
    )
    return {
        "ok": True,
        "trends": trends,
        "momentum": mom,
        "timing_confidence": tconf,
        "signals": entry_exit_signals(trends, mom, pred_t, risk, shift),
        "predictive": {
            "profit_trend": pred_t,
            "risk_spike": risk,
            "market_shift": shift,
            "opportunity_success": opp,
        },
        "feedback": _feedback_block(acc, weights),
        "context_note": "Account predictive/feedback heuristics are merged with this user-supplied series.",
    }
