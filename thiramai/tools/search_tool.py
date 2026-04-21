from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


class SearchTool:
    """
    Lightweight web-search wrapper (DuckDuckGo Instant Answer API).
    Produces compact results + summary to avoid context overflow.
    """

    def __init__(self, *, timeout_sec: float = 12.0) -> None:
        self.timeout_sec = max(2.0, float(timeout_sec))

    def search_and_summarize(self, query: str, *, top_k: int = 5) -> dict[str, Any]:
        q = str(query or "").strip()
        if not q:
            return {"ok": False, "query": "", "results": [], "summary": "", "error": "empty query"}
        limit = max(3, min(int(top_k), 5))
        data = self._duckduckgo_instant_answer(q)
        rows = self._extract_results(data, limit=limit)
        summary = self._build_summary(rows)
        return {
            "ok": True,
            "query": q,
            "results": rows,
            "summary": summary,
        }

    def _duckduckgo_instant_answer(self, query: str) -> dict[str, Any]:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {
                "q": query,
                "format": "json",
                "no_redirect": "1",
                "no_html": "1",
                "skip_disambig": "0",
            }
        )
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "thiramai/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _extract_results(self, payload: dict[str, Any], *, limit: int) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        abstract = str(payload.get("AbstractText") or "").strip()
        abstract_url = str(payload.get("AbstractURL") or "").strip()
        if abstract:
            out.append({"title": "Abstract", "url": abstract_url, "snippet": abstract[:500]})

        topics = payload.get("RelatedTopics") or []
        if isinstance(topics, list):
            for item in topics:
                if len(out) >= limit:
                    break
                if isinstance(item, dict):
                    # Flat topic
                    if isinstance(item.get("Text"), str):
                        out.append(
                            {
                                "title": str(item.get("FirstURL") or "Topic")[:120],
                                "url": str(item.get("FirstURL") or ""),
                                "snippet": str(item.get("Text") or "")[:500],
                            }
                        )
                        continue
                    # Nested topic group
                    nested = item.get("Topics")
                    if isinstance(nested, list):
                        for n in nested:
                            if len(out) >= limit:
                                break
                            if isinstance(n, dict) and isinstance(n.get("Text"), str):
                                out.append(
                                    {
                                        "title": str(n.get("FirstURL") or "Topic")[:120],
                                        "url": str(n.get("FirstURL") or ""),
                                        "snippet": str(n.get("Text") or "")[:500],
                                    }
                                )
        return out[:limit]

    def _build_summary(self, results: list[dict[str, str]]) -> str:
        if not results:
            return "No web evidence found."
        lines: list[str] = []
        for idx, row in enumerate(results[:5], start=1):
            snippet = str(row.get("snippet", "")).replace("\n", " ").strip()
            if len(snippet) > 200:
                snippet = snippet[:197] + "..."
            lines.append(f"{idx}. {snippet}")
        return "\n".join(lines)
