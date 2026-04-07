"""
Unified local-model routing: pick Ollama model by prompt shape (short vs reasoning vs long).

Does not replace ``core.router`` (tenant intent routing); this is **LLM model** selection only.
"""

from __future__ import annotations

import os
import re
from enum import Enum


class PromptKind(str, Enum):
    SHORT = "short"  # quick tasks, commands, brief answers
    REASONING = "reasoning"  # chain-of-thought friendly models
    LONG_OUTPUT = "long_output"  # reports, long prose


def _env_model(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip() or default


def ollama_model_for_kind(kind: PromptKind) -> str:
    """Resolve concrete Ollama tag from env (override per deployment)."""
    if kind is PromptKind.REASONING:
        return _env_model("THIRAMAI_OLLAMA_MODEL_REASONING", "deepseek-r1:8b")
    if kind is PromptKind.LONG_OUTPUT:
        return _env_model("THIRAMAI_OLLAMA_MODEL_LONG", "gemma2:9b")
    return _env_model("THIRAMAI_OLLAMA_MODEL_SHORT", "llama3")


def classify_prompt_kind(user_message: str) -> PromptKind:
    """
    Lightweight heuristic router (no extra LLM call — keeps latency low).

    - Reasoning: explicit reasoning / math / step-by-step cues
    - Long: very long user text or “write a detailed / full report” style
    - Short: default for voice snippets and quick ops
    """
    t = (user_message or "").strip()
    if not t:
        return PromptKind.SHORT
    low = t.lower()
    if len(t) > int((os.getenv("THIRAMAI_ROUTER_LONG_CHARS") or "900").strip() or "900"):
        return PromptKind.LONG_OUTPUT
    reasoning_re = re.compile(
        r"\b(why|how\s+do\s+you|explain\s+(your|the)\s+reasoning|step\s+by\s+step|"
        r"prove|deduce|chain\s+of\s+thought|think\s+through|what\s+if)\b",
        re.I,
    )
    if reasoning_re.search(low):
        return PromptKind.REASONING
    if re.search(
        r"\b(write|draft)\s+(a\s+)?(detailed|long|full|comprehensive)\b", low
    ) or re.search(r"\b(full\s+report|whitepaper|essay)\b", low):
        return PromptKind.LONG_OUTPUT
    return PromptKind.SHORT
