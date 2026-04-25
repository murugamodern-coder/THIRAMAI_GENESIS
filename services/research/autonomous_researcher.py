"""
Autonomous Research Agent (Self-Evolution Phase 3).

Scheduled at 3 AM IST every night via :mod:`services.scheduler`. The agent:

1. **Listens to the founder.** Reads ``learning_logs`` from the last 7 days
   to discover what the founder actually asked about (commands, brain queries,
   research starts).
2. **Tracks core domains.** Always investigates a curated list of topics
   relevant to the irrigation / oil & jaggery / agro-trading empire.
3. **Searches the web.** Uses Tavily to fetch fresh results.
4. **Synthesises a brief.** Groq distils the snippets into a structured
   "morning brief" (executive summary + per-topic insights + watchlist).
5. **Persists to long-term memory.** Stored as a high-importance
   ``morning_brief`` episode in ``jarvis_episodes`` so the Today page can
   surface it.

Invocation
----------
- Production: ``services.scheduler.ThiramaiScheduler.nightly_research_cron``
- Manual:     ``python -m services.research.autonomous_researcher``
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

_LOG = logging.getLogger(__name__)

# Static topics the founder cares about long-term. Augmented at runtime by
# whatever recent commands surface in the LearningLog.
DEFAULT_TOPICS: list[dict[str, str]] = [
    {
        "key": "drip_irrigation_automation",
        "label": "Drip irrigation automation",
        "search": "drip irrigation automation 2026 advances India",
    },
    {
        "key": "solar_panel_costs",
        "label": "Solar panel costs",
        "search": "solar panel module price India 2026 trend",
    },
    {
        "key": "jaggery_market_prices",
        "label": "Jaggery market prices",
        "search": "jaggery wholesale price Tamil Nadu Maharashtra 2026 trend",
    },
    {
        "key": "agricultural_robotics",
        "label": "Agricultural robotics",
        "search": "agricultural robotics farm automation 2026 startups breakthroughs",
    },
    {
        "key": "indian_equity_markets",
        "label": "Indian equity markets",
        "search": "Indian equity markets nifty sensex outlook this week",
    },
]

MAX_DYNAMIC_TOPICS = 5
MORNING_BRIEF_EPISODE_TYPE = "morning_brief"
MORNING_BRIEF_IMPORTANCE = 8


# ---------------------------------------------------------------------------
# Founder activity introspection
# ---------------------------------------------------------------------------


def _safe_text(value: Any, max_len: int = 280) -> str:
    if value is None:
        return ""
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
    except Exception:
        text = str(value)
    return text.strip()[:max_len]


def _extract_query_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("command", "query", "prompt", "question", "text", "search", "topic"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    args = payload.get("args") or payload.get("input") or {}
    if isinstance(args, dict):
        for key in ("command", "query", "prompt", "question", "text"):
            v = args.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def fetch_recent_founder_queries(user_id: int, *, days: int = 7, limit: int = 200) -> list[str]:
    """Pull the last ``days`` of brain commands / research queries for this user."""
    try:
        from core.database import get_session_factory
        from core.db.models import LearningLog
    except Exception as exc:  # pragma: no cover
        _LOG.warning("autonomous_researcher: models unavailable (%s)", exc)
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    out: list[str] = []
    try:
        with factory() as session:
            stmt = (
                select(LearningLog.input_data_json, LearningLog.source_type)
                .where(LearningLog.user_id == int(user_id))
                .where(LearningLog.created_at >= cutoff)
                .order_by(LearningLog.created_at.desc())
                .limit(int(limit))
            )
            rows = session.execute(stmt).all()
            for input_payload, _source in rows:
                text = _extract_query_text(input_payload)
                if text:
                    out.append(text)
    except Exception as exc:
        _LOG.warning("autonomous_researcher.fetch_recent_founder_queries failed: %s", exc)
        return []
    return out


def _stopwordy(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 5:
        return True
    stop_starts = (
        "show",
        "list",
        "open",
        "close",
        "go to",
        "what is the",
        "what's the",
        "ok",
        "thanks",
        "test",
    )
    return any(t.startswith(s) for s in stop_starts)


def derive_dynamic_topics(queries: list[str], *, limit: int = MAX_DYNAMIC_TOPICS) -> list[dict[str, str]]:
    """Group recent queries into topic candidates by frequency.

    We keep the agent honest: only queries that occurred at least twice OR
    contain a domain keyword (``oil``, ``jaggery``, etc.) become topics.
    """
    domain_keywords = (
        "oil",
        "jaggery",
        "drip",
        "irrigation",
        "solar",
        "robot",
        "robotics",
        "stock",
        "equity",
        "nifty",
        "sensex",
        "tractor",
        "pump",
        "fertilizer",
        "hydroponics",
    )
    counter: Counter[str] = Counter()
    raw_lookup: dict[str, str] = {}
    for q in queries:
        if _stopwordy(q):
            continue
        norm = " ".join(q.lower().split())[:120]
        counter[norm] += 1
        raw_lookup.setdefault(norm, q)
    candidates: list[tuple[str, int]] = []
    for norm, count in counter.most_common(50):
        is_domain = any(k in norm for k in domain_keywords)
        if count >= 2 or is_domain:
            candidates.append((norm, count))
    topics: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for norm, _count in candidates[:limit]:
        key = "founder_query__" + "_".join(norm.split()[:4])[:60]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        original = raw_lookup.get(norm, norm)
        topics.append(
            {
                "key": key,
                "label": original[:120],
                "search": original[:200],
            }
        )
    return topics


# ---------------------------------------------------------------------------
# Topic research
# ---------------------------------------------------------------------------


def research_one_topic(topic: dict[str, str], *, max_results: int = 6) -> dict[str, Any]:
    """Run a single Tavily-grounded research synthesis for ``topic``."""
    try:
        from services.llm.local_llama import research_query
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"llm_router_unavailable: {exc!s}"[:200], "topic": topic}
    res = research_query(topic.get("search") or topic.get("label") or "", max_results=max_results)
    return {
        "ok": bool(res.get("ok")),
        "topic_key": topic.get("key"),
        "topic_label": topic.get("label"),
        "synthesis": _safe_text(res.get("text"), 4000),
        "sources": res.get("sources") or [],
        "backend": res.get("backend"),
        "error": res.get("error"),
    }


# ---------------------------------------------------------------------------
# Morning brief assembly
# ---------------------------------------------------------------------------


def assemble_morning_brief(
    *,
    topic_results: list[dict[str, Any]],
    user_label: str,
) -> str:
    """Synthesise an executive morning brief out of per-topic mini-briefs.

    Uses Groq when available (smart model preferred) for tighter wording;
    otherwise falls back to local Llama. If both fail, returns a deterministic
    string concatenation so the founder *always* gets something.
    """
    if not topic_results:
        return f"Morning brief for {user_label}: no fresh data overnight."

    sections: list[str] = []
    for r in topic_results:
        if not r.get("ok"):
            continue
        label = r.get("topic_label") or r.get("topic_key") or "Untitled"
        text = r.get("synthesis") or ""
        if not text:
            continue
        sources = r.get("sources") or []
        cites = [s.get("url") for s in sources[:3] if s.get("url")]
        cite_block = ("\nSources: " + ", ".join(cites)) if cites else ""
        sections.append(f"### {label}\n{text.strip()}{cite_block}")

    if not sections:
        return f"Morning brief for {user_label}: no actionable signal in tonight's run."

    raw_combined = "\n\n".join(sections)[:14000]

    try:
        from services.llm.local_llama import (
            chat_groq,
            chat_local,
            groq_available,
            local_available,
        )
    except Exception:  # pragma: no cover
        return raw_combined

    system = (
        "You are Thiramai's overnight chief-of-staff. Compress the per-topic"
        " research notes below into a single morning brief for the founder."
        " Return clean Markdown with: ## Morning Brief — <today>; **TL;DR**"
        " (3 lines max); ## Highlights (one bullet per topic, with the most"
        " actionable signal first); ## Watchlist (concrete things to monitor"
        " today). Be brutally concise; the founder reads this on a phone."
    )
    user = f"Founder: {user_label}\nDate UTC: {datetime.now(timezone.utc).date().isoformat()}\n\nTopics:\n{raw_combined}"

    if groq_available():
        out = chat_groq(user, system=system, smart=True, max_tokens=1024)
        if out.get("ok") and out.get("text"):
            return str(out["text"]).strip()
    if local_available():
        out = chat_local(user, system=system, max_tokens=1024)
        if out.get("ok") and out.get("text"):
            return str(out["text"]).strip()

    return raw_combined


# ---------------------------------------------------------------------------
# Memory persistence
# ---------------------------------------------------------------------------


def store_brief_in_memory(
    *,
    user_id: int,
    brief_text: str,
    topic_results: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        from services.jarvis_memory_engine import get_default_engine
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"memory_engine_unavailable: {exc!s}"[:200]}
    engine = get_default_engine()
    title = f"Morning Brief — {datetime.now(timezone.utc).date().isoformat()}"
    payload = {
        "brief": brief_text,
        "topics": [
            {
                "key": r.get("topic_key"),
                "label": r.get("topic_label"),
                "ok": r.get("ok"),
                "sources": [s.get("url") for s in (r.get("sources") or [])[:5] if s.get("url")],
            }
            for r in topic_results
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return engine.store_episode(
        int(user_id),
        MORNING_BRIEF_EPISODE_TYPE,
        content=json.dumps(payload, default=str)[:8000],
        importance=MORNING_BRIEF_IMPORTANCE,
        title=title,
    )


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def _resolve_target_users(user_id: int | None) -> list[int]:
    if user_id and int(user_id) > 0:
        return [int(user_id)]
    try:
        from services.scheduler import distinct_active_user_org_pairs_sync
    except Exception:
        return []
    pairs = distinct_active_user_org_pairs_sync(50)
    return sorted({int(uid) for uid, _oid in pairs})


def run_nightly_research(
    *,
    user_id: int | None = None,
    extra_topics: list[dict[str, str]] | None = None,
    include_default_topics: bool = True,
) -> dict[str, Any]:
    """Generate and persist morning briefs.

    When ``user_id`` is omitted, runs once per active user. Returns a JSON
    summary suitable for logs and the brain-health endpoint.
    """
    targets = _resolve_target_users(user_id)
    if not targets:
        return {"ok": False, "error": "no_active_users", "ran_at": datetime.now(timezone.utc).isoformat()}

    summaries: list[dict[str, Any]] = []
    for uid in targets:
        queries = fetch_recent_founder_queries(int(uid), days=7, limit=200)
        dyn = derive_dynamic_topics(queries, limit=MAX_DYNAMIC_TOPICS)
        topics: list[dict[str, str]] = []
        if include_default_topics:
            topics.extend(DEFAULT_TOPICS)
        topics.extend(dyn)
        if extra_topics:
            topics.extend(extra_topics)

        results: list[dict[str, Any]] = []
        for topic in topics:
            try:
                results.append(research_one_topic(topic))
            except Exception as exc:
                _LOG.warning("autonomous_researcher topic '%s' failed: %s", topic.get("key"), exc)
                results.append({"ok": False, "topic_key": topic.get("key"), "error": str(exc)[:200]})

        brief = assemble_morning_brief(
            topic_results=results, user_label=f"user:{uid}"
        )
        memory = store_brief_in_memory(
            user_id=int(uid), brief_text=brief, topic_results=results
        )
        summaries.append(
            {
                "user_id": int(uid),
                "topics_run": len(topics),
                "topics_succeeded": sum(1 for r in results if r.get("ok")),
                "queries_seen": len(queries),
                "dynamic_topics": [t["key"] for t in dyn],
                "memory_persistence": memory,
                "brief_chars": len(brief or ""),
            }
        )

    return {
        "ok": True,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "users": summaries,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the autonomous research agent once.")
    parser.add_argument("--user-id", type=int, default=None, help="Target a specific user id")
    parser.add_argument(
        "--no-default-topics",
        action="store_true",
        help="Skip the canonical Thiramai topics and use only dynamic ones",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress JSON output to stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ns = _parse_args(argv)
    summary = run_nightly_research(
        user_id=ns.user_id,
        include_default_topics=(not ns.no_default_topics),
    )
    if not ns.quiet:
        print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "DEFAULT_TOPICS",
    "MAX_DYNAMIC_TOPICS",
    "MORNING_BRIEF_EPISODE_TYPE",
    "MORNING_BRIEF_IMPORTANCE",
    "assemble_morning_brief",
    "derive_dynamic_topics",
    "fetch_recent_founder_queries",
    "research_one_topic",
    "run_nightly_research",
    "store_brief_in_memory",
]
