"""Shared Tavily + LLM helpers for Part C research services."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from groq import Groq

_log = logging.getLogger("thiramai.research_common")


def tavily_search_sync(query: str, *, max_results: int = 8) -> dict[str, Any]:
    key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "error": "TAVILY_API_KEY not set"}
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=key)
        return dict(client.search(query=query[:400], max_results=max_results))
    except Exception as exc:
        _log.warning("tavily search failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def snippets_blob_from_tavily(raw: dict[str, Any], *, limit: int = 10) -> str:
    if not isinstance(raw, dict):
        return ""
    results = raw.get("results") or []
    parts: list[str] = []
    for r in results[:limit]:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "")
        body = str(r.get("content") or r.get("snippet") or "")
        url = str(r.get("url") or "")
        parts.append(f"Title: {title}\nURL: {url}\n{body}\n---")
    return "\n".join(parts)[:14000]


def groq_json_object_sync(
    *,
    system: str,
    user_content: str,
    max_tokens: int = 2048,
) -> dict[str, Any] | None:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.getenv("GROQ_SMART_MODEL") or os.getenv("GROQ_AGENT_MODEL") or "llama-3.3-70b-versatile").strip()
    try:
        client = Groq(api_key=key)
        chat = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content[:24000]},
            ],
            temperature=0.15,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        text = (chat.choices[0].message.content or "").strip()
        return json.loads(text)
    except Exception as exc:
        _log.warning("groq json failed: %s", exc)
        return None


def gemini_generate_sync(prompt: str, *, max_output_tokens: int = 8192) -> str | None:
    key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        model_name = (os.getenv("GEMINI_RESEARCH_MODEL") or "gemini-1.5-flash").strip()
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(
            prompt[:120000],
            generation_config={"max_output_tokens": max_output_tokens, "temperature": 0.2},
        )
        return (resp.text or "").strip() or None
    except Exception as exc:
        _log.warning("gemini failed: %s", exc)
        return None


def parse_json_lenient(text: str) -> dict[str, Any] | None:
    if not (text or "").strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def long_llm_sync(system: str, user_content: str, *, prefer_gemini: bool = True) -> str:
    if prefer_gemini:
        g = gemini_generate_sync(f"{system}\n\n{user_content}")
        if g:
            return g
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return user_content[:4000]
    model = (os.getenv("GROQ_SMART_MODEL") or os.getenv("GROQ_AGENT_MODEL") or "llama-3.3-70b-versatile").strip()
    try:
        client = Groq(api_key=key)
        chat = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content[:24000]},
            ],
            temperature=0.2,
            max_tokens=min(8192, 4096),
        )
        return (chat.choices[0].message.content or "").strip()
    except Exception:
        return user_content[:4000]
