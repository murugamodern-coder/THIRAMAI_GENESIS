"""Best-effort API startup warm (latency reduction for first goal / LLM paths)."""

from __future__ import annotations

from typing import Any


def run_warm_start() -> dict[str, Any]:
    from thiramai.integrations.llm_clients import warm_llm_stack

    return warm_llm_stack()
