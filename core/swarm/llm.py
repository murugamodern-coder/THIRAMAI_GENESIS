"""Thin Groq wrapper for swarm nodes (mock-friendly)."""

from __future__ import annotations

import os
from typing import Any

from groq import Groq


def groq_chat(
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is required for orchestrator swarm")
    client = Groq(api_key=key)
    m = (model or os.getenv("THIRAMAI_SWARM_MODEL") or "llama-3.3-70b-versatile").strip()
    completion = client.chat.completions.create(
        model=m,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (completion.choices[0].message.content or "").strip()
