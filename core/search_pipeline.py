"""Tavily + Groq search-seed pipeline (uses ToolRegistry)."""

from __future__ import annotations

from typing import Any

from groq import Groq
from tavily import TavilyClient

from core.errors import QueryLengthExceeded, looks_like_length_limit_error
from core.observability import log_structured
from core.policies.loader import (
    GROQ_SEARCH_SUMMARIZER_USER_MAX,
    TAVILY_API_QUERY_LIMIT,
    get_prompt,
)
from tools.registry import ToolRegistry


def _ascii_debug(s: str, max_chars: int = 160) -> str:
    return ascii((s or "")[:max_chars])


def clip_for_tavily_api(q: str) -> str:
    return (q or "").strip()[:TAVILY_API_QUERY_LIMIT]


def clip_for_groq_search_summarizer_user(user_message: str) -> str:
    u = (user_message or "").strip()
    return u[:GROQ_SEARCH_SUMMARIZER_USER_MAX] if u else u


def fallback_search_seed(user_message: str) -> str:
    u = (user_message or "").strip()
    if not u:
        return clip_for_tavily_api("industrial technology investment outlook 2026")
    words = u.split()
    seed = " ".join(words[:25]).strip()
    return clip_for_tavily_api(seed if seed else "industrial technology investment outlook 2026")


def summarize_for_search_query(
    registry: ToolRegistry, client: Groq, user_message: str
) -> str:
    u = (user_message or "").strip()
    if not u:
        return fallback_search_seed(u)
    if len(u) <= 200 and len(u.split()) <= 22:
        return clip_for_tavily_api(u)

    u_for_seed = clip_for_groq_search_summarizer_user(u)
    system = get_prompt("SEARCH_QUERY_SUMMARIZER_SYSTEM")
    try:
        completion = registry.groq_search_seed(
            client,
            system=system,
            user=f"User brief:\n\n{u_for_seed}",
        )
        out = (completion.choices[0].message.content or "").strip()
        out = out.strip('"').strip("'").split("\n")[0].strip()
        words = out.split()
        if len(words) > 22:
            out = " ".join(words[:20])
        if not out:
            return fallback_search_seed(u)
        return clip_for_tavily_api(out)
    except Exception as exc:
        if looks_like_length_limit_error(exc):
            raise QueryLengthExceeded(
                "The request was too long for the model while building a search query. "
                "Try a shorter brief (under 5000 characters) or simplify the topic."
            ) from exc
        log_structured(
            "search_pipeline.summarization_failed",
            error=_ascii_debug(str(exc), 240),
            fallback="search_seed",
        )
        return fallback_search_seed(u)


def topic_search_queries(search_seed: str) -> tuple[str, ...]:
    s = clip_for_tavily_api(search_seed)
    if not s:
        return (clip_for_tavily_api("industrial technology investment outlook 2026"),)
    primary = clip_for_tavily_api(s)
    queries: list[str] = [primary]
    if len(s) > 40:
        extra = clip_for_tavily_api(s.rstrip() + " market suppliers specifications 2026")
        if extra.strip() != primary.strip():
            queries.append(extra)
    return tuple(queries)


def format_tavily_results(raw: dict[str, Any]) -> tuple[str, bool]:
    results = raw.get("results") or []
    if not results:
        return ("_No results for this query._", False)
    lines: list[str] = []
    for i, item in enumerate(results[:8], start=1):
        title = (item.get("title") or "Untitled").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or item.get("raw_content") or "").strip()
        if len(content) > 1200:
            content = content[:1200] + "..."
        lines.append(f"##### Source {i}: {title}\n- URL: {url}\n- Excerpt: {content}\n")
    return "\n".join(lines), True


def gather_live_search_context(
    registry: ToolRegistry,
    tavily: TavilyClient,
    groq_client: Groq,
    user_message: str,
) -> tuple[str, bool]:
    search_seed = summarize_for_search_query(registry, groq_client, user_message)
    search_seed = clip_for_tavily_api(search_seed)
    _prev = search_seed if len(search_seed) <= 120 else search_seed[:120] + "..."
    log_structured(
        "search_pipeline.tavily_seed",
        seed_chars=len(search_seed),
        cap=TAVILY_API_QUERY_LIMIT,
        preview=_ascii_debug(_prev, 200),
    )

    parts: list[str] = []
    any_hit = False
    for idx, q in enumerate(topic_search_queries(search_seed), start=1):
        tavily_query = clip_for_tavily_api(q)
        try:
            raw = registry.tavily_search(tavily, query=tavily_query)
        except Exception as exc:
            if looks_like_length_limit_error(exc):
                raise QueryLengthExceeded(
                    "The search API rejected the query length. "
                    "Try a shorter or clearer brief (under 5000 characters)."
                ) from exc
            raise
        block, has = format_tavily_results(raw)
        if has:
            any_hit = True
        parts.append(f"#### Topic search {idx}: `{tavily_query}`\n{block}")
    merged = "\n\n".join(parts)
    if not any_hit:
        merged = (
            "NO LIVE DATA for the topic searches. State **Awaiting Live Data** where market facts are needed.\n\n"
            + merged
        )
    return merged, any_hit
