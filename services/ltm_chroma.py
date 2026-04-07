"""
Long-term tool memory on ChromaDB (vector search over Prompt → Action → Outcome → Error).

Enable with ``THIRAMAI_LTM_ENABLED=1``. Persist path: ``THIRAMAI_CHROMA_PATH`` (default ``var/chroma_ltm``).
Tenant-isolated via metadata ``organization_id`` + ``success`` flag for failure retrieval.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

COLLECTION = "thiramai_tool_memory"

_log = __import__("logging").getLogger(__name__)


def ltm_enabled() -> bool:
    return (os.getenv("THIRAMAI_LTM_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def chroma_path() -> Path:
    raw = (os.getenv("THIRAMAI_CHROMA_PATH") or "var/chroma_ltm").strip()
    return Path(__file__).resolve().parents[1] / raw


def _collection():
    if not ltm_enabled():
        return None
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError:
        _log.warning("ltm_chroma: chromadb not installed")
        return None
    path = chroma_path()
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(path),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=COLLECTION,
        metadata={"description": "THIRAMAI tool execution memory"},
    )


def _doc_text(*, prompt: str, tool_id: str, action: dict[str, Any], ok: bool, error: str) -> str:
    return (
        f"Prompt context:\n{(prompt or '').strip()[:8000]}\n\n"
        f"Tool: {tool_id}\n"
        f"Action:\n{json.dumps(action, ensure_ascii=False, default=str)[:8000]}\n\n"
        f"Outcome: {'success' if ok else 'failure'}\n"
        f"Error:\n{(error or '').strip()[:4000]}"
    )


def record_tool_execution(
    *,
    organization_id: int,
    prompt_context: str,
    tool_id: str,
    action: dict[str, Any],
    outcome_ok: bool,
    error_message: str = "",
    correlation_id: str | None = None,
) -> None:
    """Upsert-like add of one execution record (embedding over full document)."""
    coll = _collection()
    if coll is None:
        return
    oid = str(int(organization_id))
    doc = _doc_text(
        prompt=prompt_context,
        tool_id=tool_id,
        action=action,
        ok=outcome_ok,
        error=error_message,
    )
    mid = str(uuid.uuid4())
    meta: dict[str, Any] = {
        "organization_id": oid,
        "tool_id": tool_id,
        "success": int(bool(outcome_ok)),
        "correlation_id": (correlation_id or "")[:128],
    }
    try:
        coll.add(ids=[mid], documents=[doc], metadatas=[meta])
        _log.debug("ltm_chroma: recorded id=%s tool=%s ok=%s", mid, tool_id, outcome_ok)
    except Exception as exc:
        _log.warning("ltm_chroma: add failed: %s", exc)


def search_similar_failures(
    *,
    organization_id: int,
    query_text: str,
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """Semantic search limited to **failed** executions for this org."""
    coll = _collection()
    if coll is None:
        return []
    oid = str(int(organization_id))
    q = (query_text or "").strip()[:8000]
    if not q:
        return []
    n = max(1, min(20, int(n_results)))
    t0 = time.perf_counter()
    try:
        res = coll.query(
            query_texts=[q],
            n_results=n,
            where={
                "$and": [
                    {"organization_id": {"$eq": oid}},
                    {"success": {"$eq": 0}},
                ]
            },
        )
    except Exception as exc:
        _log.warning("ltm_chroma: query failed: %s", exc)
        return []
    elapsed_ms = (time.perf_counter() - t0) * 1000
    try:
        from services.ltm_self_tune import maybe_flag_slow_ltm_after_query

        maybe_flag_slow_ltm_after_query(
            organization_id=int(organization_id),
            query_ms=elapsed_ms,
            correlation_id=None,
        )
    except Exception:
        pass
    out: list[dict[str, Any]] = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    dists = (res.get("distances") or [[]])[0] if res.get("distances") else [None] * len(ids)
    for i, doc_id in enumerate(ids):
        out.append(
            {
                "id": doc_id,
                "document": docs[i] if i < len(docs) else "",
                "distance": dists[i] if i < len(dists) else None,
            }
        )
    return out


def format_mitigation_block(*, organization_id: int, user_query: str) -> str:
    """
    If similar failures exist, return markdown for the executive pack including explicit
    **Mitigation strategies** (deterministic heuristics from retrieved text).
    """
    hits = search_similar_failures(organization_id=organization_id, query_text=user_query, n_results=4)
    if not hits:
        return ""
    lines = [
        "## Long-term memory — similar past failures",
        "",
        "The following **retrieved failures** are semantically close to the current user request. "
        "You must **acknowledge** them and include a **Mitigation strategy** section in your plan "
        "(concrete checks before repeating the same mistake).",
        "",
    ]
    for idx, h in enumerate(hits, start=1):
        snippet = (h.get("document") or "")[:1200].strip()
        if not snippet:
            continue
        strat = _mitigation_from_snippet(snippet)
        lines.append(f"### Past failure #{idx}")
        lines.append(f"> {snippet.replace(chr(10), ' ')[:900]}…" if len(snippet) > 900 else f"> {snippet}")
        lines.append("")
        lines.append(f"**Mitigation strategy:** {strat}")
        lines.append("")
    lines.append("---")
    return "\n".join(lines).strip()


def _mitigation_from_snippet(snippet: str) -> str:
    low = snippet.lower()
    if "insufficient" in low or "stock" in low and "not" in low:
        return "Verify on-hand quantity and SKU spelling/location before confirming a sale; offer alternatives if low."
    if "billing" in low and "pause" in low:
        return "Check factory billing-hold status before promising inventory movement; surface hold reason to the user."
    if "policy" in low or "403" in low or "blocked" in low:
        return "Confirm caller role and policy gate; prefer PROPOSE/HITL path instead of auto-execution."
    if "fractional" in low or "whole number" in low:
        return "Quantities must be whole units; validate before posting."
    return "Re-read constraints in the retrieved error, double-check prerequisites, and prefer a conservative or HITL path."
