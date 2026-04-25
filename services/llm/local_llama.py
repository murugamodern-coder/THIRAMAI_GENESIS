"""
Local Llama (Ollama) client + smart query router.

Server-side install (Linux, one-time):
    apt install ollama
    ollama pull llama3.1:8b

Routing policy
--------------
- *simple* (greetings, factoid Q&A, formatting, classification)
    → Local Llama (Ollama). Free, low latency, keeps cloud cost flat.
- *complex* (multi-step reasoning, business decisions, code, math)
    → Groq (`llama-3.1-8b-instant` / `llama-3.3-70b-versatile`).
- *research* (anything that benefits from fresh web knowledge)
    → Tavily search + Groq synthesis.

Public API
----------
- :class:`LocalLlamaClient`     — thin Ollama HTTP wrapper
- :func:`classify_complexity`   — heuristic + optional Groq classifier
- :func:`route_query`           — high-level entry point that picks a backend
- :func:`chat_local`            — convenience wrapper over the local model
- :func:`chat_groq`             — convenience wrapper over Groq
- :func:`research_query`        — Tavily + Groq synthesis

All functions return JSON-safe dicts; nothing raises on missing deps.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

_LOG = logging.getLogger(__name__)

# Default models (override via env)
DEFAULT_LOCAL_MODEL = (os.getenv("OLLAMA_MODEL") or "llama3.1:8b").strip()
DEFAULT_GROQ_FAST_MODEL = (os.getenv("GROQ_FAST_MODEL") or "llama-3.1-8b-instant").strip()
DEFAULT_GROQ_SMART_MODEL = (
    os.getenv("GROQ_SMART_MODEL")
    or os.getenv("GROQ_AGENT_MODEL")
    or "llama-3.3-70b-versatile"
).strip()

# Approximate token thresholds (chars per token ~4)
_COMPLEX_CHAR_THRESHOLD = 1200

# Heuristic keyword sets
_RESEARCH_KEYWORDS = {
    "latest",
    "today",
    "news",
    "research",
    "compare",
    "market price",
    "trend",
    "analyst",
    "forecast",
    "report",
    "this week",
    "this month",
    "current price",
    "live price",
    "search the web",
    "find papers",
    "find news",
    "investigate",
    "study",
}
_COMPLEX_KEYWORDS = {
    "plan",
    "strategy",
    "design",
    "architect",
    "refactor",
    "optimize",
    "explain step by step",
    "step-by-step",
    "trade-off",
    "tradeoff",
    "decision",
    "calculate",
    "compute",
    "analyze",
    "analyse",
    "debug",
    "diagnose",
    "root cause",
    "code review",
    "write code",
    "implement",
    "schema",
    "migration",
    "algorithm",
}
_SIMPLE_KEYWORDS = {
    "hi",
    "hello",
    "thanks",
    "ok",
    "yes",
    "no",
    "translate",
    "summarize",
    "what is",
    "define",
    "spell",
    "format",
    "rephrase",
}


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------


class LocalLlamaClient:
    """Minimal blocking client for an Ollama server.

    Endpoints used:
    - ``POST /api/generate`` for non-streaming completions.
    - ``GET  /api/tags`` for the health probe.

    Uses ``urllib`` rather than ``httpx`` to avoid pulling extra deps; if a
    request library is missing for some reason, methods return informative
    error payloads.
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.host = (host or os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.model = (model or DEFAULT_LOCAL_MODEL).strip()
        self.timeout = float(timeout)

    def health(self) -> dict[str, Any]:
        try:
            import urllib.error
            import urllib.request

            req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=min(self.timeout, 5.0)) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
                models = [m.get("name") for m in (data.get("models") or [])]
                return {"ok": True, "host": self.host, "models": models, "default": self.model}
        except Exception as exc:
            return {"ok": False, "host": self.host, "error": str(exc)[:200]}

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        try:
            import urllib.error
            import urllib.request
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "error": f"urllib_unavailable: {exc!s}"[:200]}
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": (prompt or "")[:24000],
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
            },
        }
        if system:
            body["system"] = str(system)[:4000]
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                f"{self.host}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
                text = (payload.get("response") or "").strip()
                return {
                    "ok": True,
                    "text": text,
                    "model": self.model,
                    "host": self.host,
                    "prompt_eval_count": payload.get("prompt_eval_count"),
                    "eval_count": payload.get("eval_count"),
                }
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200], "host": self.host, "model": self.model}


_DEFAULT_CLIENT: LocalLlamaClient | None = None


def get_default_client() -> LocalLlamaClient:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = LocalLlamaClient()
    return _DEFAULT_CLIENT


def local_available() -> bool:
    """Quick health probe; cached call would be cheap, but kept honest here."""
    try:
        return bool(get_default_client().health().get("ok"))
    except Exception:
        return False


def groq_available() -> bool:
    return bool((os.getenv("GROQ_API_KEY") or "").strip())


def tavily_available() -> bool:
    return bool((os.getenv("TAVILY_API_KEY") or "").strip())


# ---------------------------------------------------------------------------
# Complexity classifier
# ---------------------------------------------------------------------------


def _matches_any(text: str, keywords: set[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def classify_complexity(query: str) -> dict[str, Any]:
    """Heuristic O(1) classifier.

    Returns ``{"category": "simple"|"complex"|"research", "reason": str}``.
    Uses keyword lists and length so we never spend an API call to decide
    where to *route* — that defeats the cost optimisation.
    """
    q = (query or "").strip()
    if not q:
        return {"category": "simple", "reason": "empty"}

    if _matches_any(q, _RESEARCH_KEYWORDS):
        return {"category": "research", "reason": "research_keyword"}

    if len(q) > _COMPLEX_CHAR_THRESHOLD:
        return {"category": "complex", "reason": "length"}

    if _matches_any(q, _COMPLEX_KEYWORDS):
        return {"category": "complex", "reason": "complex_keyword"}

    if _matches_any(q, _SIMPLE_KEYWORDS) or len(q.split()) <= 8:
        return {"category": "simple", "reason": "simple_keyword_or_short"}

    # Multiline / multi-sentence queries usually deserve a smarter model
    if q.count("\n") >= 2 or len(re.findall(r"[.?!]\s", q)) >= 3:
        return {"category": "complex", "reason": "multi_part"}

    return {"category": "simple", "reason": "default_short_form"}


# ---------------------------------------------------------------------------
# Backend chats
# ---------------------------------------------------------------------------


def chat_local(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Send a query to the local Ollama server."""
    client = get_default_client()
    out = client.generate(
        prompt, system=system, max_tokens=max_tokens, temperature=temperature
    )
    out["backend"] = "local_llama"
    return out


def chat_groq(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    smart: bool = True,
) -> dict[str, Any]:
    """Call Groq's chat completion endpoint.

    When ``smart=True`` we use ``llama-3.3-70b-versatile`` (or
    ``GROQ_SMART_MODEL``); otherwise the fast 8B model.
    """
    if not groq_available():
        return {"ok": False, "error": "GROQ_API_KEY missing", "backend": "groq"}
    chosen = (
        model
        or (DEFAULT_GROQ_SMART_MODEL if smart else DEFAULT_GROQ_FAST_MODEL)
    ).strip()
    try:
        from groq import Groq  # type: ignore[import-not-found]
    except Exception as exc:
        return {"ok": False, "error": f"groq_sdk_missing: {exc!s}"[:200], "backend": "groq"}
    try:
        client = Groq(api_key=(os.getenv("GROQ_API_KEY") or "").strip())
        messages = []
        if system:
            messages.append({"role": "system", "content": str(system)[:4000]})
        messages.append({"role": "user", "content": (prompt or "")[:24000]})
        chat = client.chat.completions.create(
            model=chosen,
            messages=messages,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
        )
        text = (chat.choices[0].message.content or "").strip()
        return {"ok": True, "text": text, "backend": "groq", "model": chosen}
    except Exception as exc:
        _LOG.warning("groq chat failed: %s", exc)
        return {"ok": False, "error": str(exc)[:200], "backend": "groq", "model": chosen}


def research_query(
    query: str,
    *,
    max_results: int = 6,
    max_synth_tokens: int = 1024,
) -> dict[str, Any]:
    """Tavily-backed research synthesised by Groq.

    1. Search Tavily for fresh web context.
    2. Pass top-K snippets to Groq with a research-summary system prompt.
    3. Return ``{ok, text, sources, backend}``.

    Falls back to ``chat_groq`` (or ``chat_local`` if Groq missing) when
    Tavily is unavailable, so the caller still gets *something*.
    """
    sources: list[dict[str, Any]] = []
    snippets: list[str] = []
    if tavily_available():
        try:
            from tavily import TavilyClient  # type: ignore[import-not-found]

            client = TavilyClient(api_key=(os.getenv("TAVILY_API_KEY") or "").strip())
            res = dict(client.search(query=(query or "")[:400], max_results=int(max_results)) or {})
            for it in (res.get("results") or [])[:max_results]:
                src = {
                    "title": str(it.get("title") or "")[:200],
                    "url": str(it.get("url") or ""),
                    "snippet": str(it.get("content") or it.get("snippet") or "")[:1200],
                    "score": it.get("score"),
                }
                sources.append(src)
                if src["snippet"]:
                    snippets.append(f"- {src['title']}: {src['snippet']}")
        except Exception as exc:
            _LOG.warning("tavily search failed: %s", exc)

    # If Tavily produced nothing, fall back to a non-grounded reply
    if not snippets:
        if groq_available():
            out = chat_groq(query, system="You are a helpful research assistant.", smart=True)
            out["sources"] = sources
            out["backend"] = "groq_no_tavily"
            return out
        out = chat_local(query, system="You are a helpful research assistant.")
        out["sources"] = sources
        out["backend"] = "local_no_tavily"
        return out

    system = (
        "You are a senior research analyst writing crisp, cite-aware briefs for a"
        " busy founder. Use ONLY the snippets supplied below; if a snippet is"
        " irrelevant ignore it. Format: 1) TL;DR (2-3 lines), 2) Key Facts"
        " (bullets), 3) Implications for Indian SMB, 4) What to watch next."
    )
    user = (
        f"Question: {query}\n\nSnippets:\n"
        + "\n".join(snippets)[:18000]
        + "\n\nProduce the brief now."
    )
    if groq_available():
        out = chat_groq(user, system=system, smart=True, max_tokens=max_synth_tokens)
    else:
        out = chat_local(user, system=system, max_tokens=max_synth_tokens)
    out["sources"] = sources
    return out


# ---------------------------------------------------------------------------
# Top-level router
# ---------------------------------------------------------------------------


def route_query(
    query: str,
    *,
    system: str | None = None,
    force: str | None = None,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """High-level routing entry point.

    - ``force="local"|"groq"|"research"`` overrides the heuristic.
    - The router degrades gracefully: if the chosen backend is unavailable
      we fall back in this order: local → groq fast → groq smart → research.
    """
    decision = (force or "").lower().strip() or classify_complexity(query)["category"]
    started_with = decision

    if decision == "research":
        if tavily_available() and (groq_available() or local_available()):
            out = research_query(query)
            out["routed_via"] = "research"
            out["category"] = started_with
            return out
        decision = "complex"

    if decision == "complex":
        if groq_available():
            out = chat_groq(query, system=system, smart=True, max_tokens=max_tokens)
            out["routed_via"] = "groq_smart"
            out["category"] = started_with
            return out
        decision = "simple"

    # simple / fallback
    if local_available():
        out = chat_local(query, system=system, max_tokens=max_tokens)
        out["routed_via"] = "local_llama"
        out["category"] = started_with
        return out
    if groq_available():
        out = chat_groq(query, system=system, smart=False, max_tokens=max_tokens)
        out["routed_via"] = "groq_fast_fallback"
        out["category"] = started_with
        return out
    return {
        "ok": False,
        "error": "no_backend_available",
        "category": started_with,
        "routed_via": "none",
    }


def get_status() -> dict[str, Any]:
    """Capability snapshot used by the brain-health endpoint."""
    health = get_default_client().health()
    return {
        "local": health,
        "groq_configured": groq_available(),
        "tavily_configured": tavily_available(),
        "default_local_model": DEFAULT_LOCAL_MODEL,
        "default_groq_smart_model": DEFAULT_GROQ_SMART_MODEL,
        "default_groq_fast_model": DEFAULT_GROQ_FAST_MODEL,
    }


__all__ = [
    "DEFAULT_GROQ_FAST_MODEL",
    "DEFAULT_GROQ_SMART_MODEL",
    "DEFAULT_LOCAL_MODEL",
    "LocalLlamaClient",
    "chat_groq",
    "chat_local",
    "classify_complexity",
    "get_default_client",
    "get_status",
    "groq_available",
    "local_available",
    "research_query",
    "route_query",
    "tavily_available",
]
