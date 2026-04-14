"""Attach confidence + structured AI safety metadata to agent/chat payloads."""

from __future__ import annotations

import os
import re
from typing import Any


def _min_confidence_threshold() -> float:
    raw = (os.getenv("THIRAMAI_AI_MIN_CONFIDENCE") or "0").strip()
    try:
        v = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, min(v, 0.99))


def estimate_confidence(*, narrative: str, sources: list[str]) -> float:
    base = 0.52
    base += min(0.35, 0.04 * min(len(sources), 8))
    low = re.search(r"\b(unknown|insufficient|cannot verify|not sure)\b", narrative, re.I)
    if low:
        base -= 0.18
    return max(0.05, min(0.95, base))


def apply_ai_safety_envelope(payload: dict[str, Any], *, narrative: str, sources: list[str]) -> dict[str, Any]:
    conf = estimate_confidence(narrative=narrative or "", sources=sources)
    thr = _min_confidence_threshold()
    safe_narrative = narrative
    if thr > 0 and conf < thr:
        safe_narrative = "Not enough verified data to answer safely. Try a narrower question or attach sources."
    payload["confidence_score"] = round(conf, 3)
    payload["ai_safety"] = {
        "confidence_score": round(conf, 3),
        "min_confidence_threshold": thr,
        "sources": sources[:24],
        "structured": True,
        "low_confidence_suppressed": bool(thr > 0 and conf < thr),
    }
    if payload.get("narrative") is not None:
        payload["narrative"] = safe_narrative
    if payload.get("response") is not None:
        payload["response"] = safe_narrative
    return payload
