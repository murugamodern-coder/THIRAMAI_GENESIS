"""Intent classification for Thiramai commands.

Primary mode is deterministic rule-based scoring.
Optional LLM refinement can be enabled later via env:
- THIRAMAI_INTENT_ENABLE_LLM=1
"""

from __future__ import annotations

import os
import re
from typing import Literal

from services.research_common import groq_json_object_sync

IntentType = Literal["personal", "business", "research", "money", "build"]
_INTENTS: tuple[IntentType, ...] = ("personal", "business", "research", "money", "build")

_KEYWORDS: dict[IntentType, tuple[str, ...]] = {
    "personal": (
        "personal",
        "my",
        "task",
        "habit",
        "health",
        "meeting",
        "reminder",
        "plan",
    ),
    "business": (
        "invoice",
        "inventory",
        "customer",
        "gst",
        "billing",
        "revenue",
        "profit",
        "supplier payment",
    ),
    "research": (
        "find",
        "research",
        "analyze",
        "compare",
        "cheapest",
        "supplier",
        "market",
        "india",
    ),
    "money": (
        "stock",
        "trade",
        "buy",
        "sell",
        "nse",
        "bse",
        "portfolio",
        "signal",
    ),
    "build": (
        "build",
        "create app",
        "generate code",
        "deploy",
        "website",
        "automation",
        "tool",
        "agent",
    ),
}


def _rule_scores(text: str) -> dict[IntentType, int]:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    scores: dict[IntentType, int] = {k: 0 for k in _INTENTS}
    if not t:
        return scores
    for intent, keys in _KEYWORDS.items():
        for k in keys:
            if k in t:
                scores[intent] += 2 if " " in k else 1
    # Strong phrase hints.
    if "buy stock" in t or "sell stock" in t:
        scores["money"] += 3
    if "create invoice" in t:
        scores["business"] += 3
    if "find supplier" in t:
        scores["research"] += 3
    return scores


def _pick_intent(scores: dict[IntentType, int]) -> IntentType:
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_intent, top_score = ordered[0]
    if top_score <= 0:
        return "research"
    # deterministic tie-break priority
    for cand in ("money", "build", "business", "personal", "research"):
        if scores[cand] == top_score:
            return cand
    return top_intent


def _llm_enabled() -> bool:
    return (os.getenv("THIRAMAI_INTENT_ENABLE_LLM") or "").strip().lower() in {"1", "true", "yes", "on"}


def _llm_classify(text: str) -> IntentType | None:
    parsed = groq_json_object_sync(
        system=(
            "Classify user command into one intent only. "
            'Allowed intents: personal, business, research, money, build. '
            'Return strict JSON: {"intent":"..."}'
        ),
        user_content=f"Command: {text}",
        max_tokens=60,
    )
    if not isinstance(parsed, dict):
        return None
    raw = str(parsed.get("intent") or "").strip().lower()
    if raw in _INTENTS:
        return raw  # type: ignore[return-value]
    return None


def classify_intent(command_text: str) -> IntentType:
    """Rule-first intent classifier with optional LLM refinement."""
    scores = _rule_scores(command_text)
    rule_intent = _pick_intent(scores)
    if not _llm_enabled():
        return rule_intent
    refined = _llm_classify(command_text)
    return refined or rule_intent

