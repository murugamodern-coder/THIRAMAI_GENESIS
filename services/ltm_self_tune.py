"""
Stage 5 — Recursive memory tuning (AlphaDev-style): measure Chroma LTM query latency and emit
a **self-coder brief** so the agent can patch ``services/ltm_chroma.py`` / embedding settings.

Does not auto-mutate production indexes without human merge — returns actionable text + env hints.
"""

from __future__ import annotations

import os
import time
from typing import Any

from core.sovereign_journal import record_background_action, record_cot_step

_LOG = __import__("logging").getLogger(__name__)


def benchmark_ltm_query_ms(
    *,
    organization_id: int,
    query: str = "retail stock sale billing policy blocked insufficient quantity",
    iterations: int = 3,
) -> dict[str, Any]:
    from services import ltm_chroma

    if not ltm_chroma.ltm_enabled():
        return {"ok": False, "skipped": True, "reason": "THIRAMAI_LTM_ENABLED off"}
    times: list[float] = []
    err = ""
    for _ in range(max(1, min(10, iterations))):
        t0 = time.perf_counter()
        try:
            _ = ltm_chroma.search_similar_failures(
                organization_id=int(organization_id),
                query_text=query,
                n_results=8,
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            break
        times.append((time.perf_counter() - t0) * 1000)
    if err:
        return {"ok": False, "error": err}
    avg = sum(times) / len(times) if times else 0.0
    slow_ms = float((os.getenv("THIRAMAI_LTM_SLOW_MS") or "450").strip() or "450")
    slow = avg > slow_ms
    return {
        "ok": True,
        "avg_ms": round(avg, 2),
        "samples": [round(t, 2) for t in times],
        "slow": slow,
        "threshold_ms": slow_ms,
    }


def build_self_coder_memory_brief(*, organization_id: int) -> str:
    """
    Markdown instructions the Self-Coder / kernel sandbox can use to improve LTM infra.
    """
    bench = benchmark_ltm_query_ms(organization_id=int(organization_id))
    record_cot_step(
        agent="ltm_self_tune",
        phase="benchmark",
        detail=str(bench),
        organization_id=int(organization_id),
    )
    lines = [
        "# LTM (Chroma) self-tuning brief",
        "",
        f"- Benchmark: `{bench}`",
        "",
        "## If queries are slow",
        "- Consider reducing ``n_results`` in ``search_similar_failures`` default (trade recall vs latency).",
        "- Prefer smaller embedding batches in ``record_tool_execution`` (already one-doc adds).",
        "- Ensure ``THIRAMAI_CHROMA_PATH`` is on local SSD; avoid network filesystems.",
        "- Evaluate Chroma persistent store fragmentation: scheduled maintenance window to compact/rebuild collection.",
        "- Optional: switch embedding model via Chroma embedding function configuration (requires code change in ``_collection()``).",
        "",
        "## Safe code touchpoints",
        "- ``services/ltm_chroma.py`` — collection metadata, query ``where`` clause, caps on document size.",
        "- ``core/context_engine.py`` — how ``format_mitigation_block`` is injected (token budget).",
        "",
        "## Research prompts (for the agent)",
        "- \"ChromaDB HNSW tuning parameters persistent client\"",
        "- \"sentence-transformers smaller models vs latency for retrieval\"",
        "",
    ]
    if bench.get("slow"):
        record_background_action(
            category="ltm",
            summary=f"LTM query slow avg_ms={bench.get('avg_ms')} — self-tune recommended",
            organization_id=int(organization_id),
            meta={"benchmark": bench},
        )
    return "\n".join(lines)


def maybe_flag_slow_ltm_after_query(
    *,
    organization_id: int,
    query_ms: float,
    correlation_id: str | None = None,
) -> None:
    """Hook from ltm_chroma.search_similar_failures when timing is available (optional future wire)."""
    try:
        thr = float((os.getenv("THIRAMAI_LTM_SLOW_MS") or "450").strip() or "450")
    except ValueError:
        thr = 450.0
    if query_ms <= thr:
        return
    record_background_action(
        category="ltm",
        summary=f"Slow LTM retrieval {query_ms:.1f}ms (threshold {thr}ms)",
        organization_id=int(organization_id),
        meta={"correlation_id": (correlation_id or "")[:128]},
    )
