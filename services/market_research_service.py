"""
Solar manufacturing **DPR** market research via Tavily (live web). Results are cached under ``var/``
to avoid blocking dashboards on every request.

Dashboard JSON schema: ``thiramai.solar_dpr_market_research.v1`` (see ``build_solar_dpr_dashboard_block``).
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.db.provisioning import MASS_SUCCESS_AGRO_AGENCY_ID

_ROOT = Path(__file__).resolve().parents[1]
_VAR = _ROOT / "var"
_CACHE_FILE = _VAR / "solar_dpr_tavily_cache.json"

DEFAULT_CACHE_TTL_SEC = int((os.getenv("THIRAMAI_SOLAR_DPR_CACHE_TTL_SEC") or "2700").strip() or "2700")
DEFAULT_SOLAR_PROGRESS_PCT = 28

SOLAR_DPR_QUERIES: tuple[tuple[str, str], ...] = (
    ("setup_cost_india_2026", "Solar Panel Manufacturing setup cost India 2026"),
    ("pm_kusum_subsidies", "Govt subsidies for Solar PM-KUSUM"),
    ("machinery_suppliers_tamil_nadu", "Machinery suppliers in Tamil Nadu solar panel manufacturing"),
)

_LAKH = 100_000.0
_CRORE = 10_000_000.0


def _parse_inr_band_from_text(text: str) -> tuple[float | None, float | None]:
    """Best-effort lakh/crore hints from snippets (not audited financial advice)."""
    t = (text or "").lower().replace(",", " ")
    lows: list[float] = []
    highs: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(crore|lakh|lac)\b", t):
        a, b, unit = float(m.group(1)), float(m.group(2)), m.group(3)
        mul = _CRORE if unit == "crore" else _LAKH
        lows.append(a * mul)
        highs.append(b * mul)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(crore|lakh|lac)\b", t):
        v, unit = float(m.group(1)), m.group(2)
        mul = _CRORE if unit == "crore" else _LAKH
        x = v * mul
        lows.append(x)
        highs.append(x)
    if not lows:
        return None, None
    return min(lows), max(highs) if highs else max(lows)


def _tavily_search_one(query: str, *, max_results: int = 5) -> dict[str, Any]:
    key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "skipped": True, "detail": "TAVILY_API_KEY unset", "results": []}
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=key)
        raw = client.search(query, max_results=max_results)
    except Exception as exc:
        return {"ok": False, "skipped": False, "detail": f"{type(exc).__name__}: {exc}", "results": []}
    results: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for item in raw.get("results") or []:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "title": (item.get("title") or "")[:500],
                    "url": item.get("url"),
                    "content": (item.get("content") or "")[:2000],
                    "score": item.get("score"),
                }
            )
    return {"ok": True, "skipped": False, "detail": None, "results": results}


def _run_all_tavily_queries() -> dict[str, Any]:
    by_key: dict[str, dict[str, Any]] = {}
    combined_text = ""

    def _job(key: str, q: str) -> tuple[str, str, dict[str, Any]]:
        return key, q, _tavily_search_one(q)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(_job, k, q): (k, q) for k, q in SOLAR_DPR_QUERIES}
        for fut in as_completed(futs):
            k, q = futs[fut]
            try:
                k2, q2, block = fut.result()
            except Exception as exc:
                k2, q2, block = k, q, {"ok": False, "detail": str(exc), "results": []}
            row = {
                "key": k2,
                "query": q2,
                "ok": bool(block.get("ok")),
                "skipped": bool(block.get("skipped")),
                "detail": block.get("detail"),
                "results": block.get("results") or [],
            }
            by_key[k2] = row
            for r in block.get("results") or []:
                combined_text += " " + str(r.get("content") or "") + " " + str(r.get("title") or "")

    out_queries = [by_key[k] for k, _ in SOLAR_DPR_QUERIES if k in by_key]

    low, high = _parse_inr_band_from_text(combined_text)
    mid: float | None = None
    if low is not None and high is not None:
        mid = (low + high) / 2.0
    elif low is not None:
        mid = low

    return {
        "queries": out_queries,
        "initial_capex_estimate_inr": round(mid, 2) if mid is not None else None,
        "initial_capex_low_inr": round(low, 2) if low is not None else None,
        "initial_capex_high_inr": round(high, 2) if high is not None else None,
        "initial_capex_note": (
            "Heuristic range from Tavily snippets (lakh/crore). Not a substitute for a stamped DPR or CA sign-off."
            if mid is not None
            else "No clear lakh/crore figures parsed; see query results for qualitative context."
        ),
    }


def format_solar_dpr_bundle_markdown(bundle: dict[str, Any]) -> str:
    """User-facing Markdown summary for chat / orchestrator (from ``fetch_solar_dpr_research_bundle``)."""
    if not isinstance(bundle, dict):
        return "**Solar market research:** (no data)"
    lines: list[str] = ["## Solar DPR market research"]
    low = bundle.get("initial_capex_low_inr")
    high = bundle.get("initial_capex_high_inr")
    mid = bundle.get("initial_capex_estimate_inr")
    note = bundle.get("initial_capex_note") or ""
    if mid is not None:
        if low is not None and high is not None and low != high:
            lines.append(
                f"- **Indicative capex band (heuristic):** ₹{low:,.0f} – ₹{high:,.0f} (mid ≈ ₹{mid:,.0f})"
            )
        else:
            lines.append(f"- **Indicative capex (heuristic):** ₹{mid:,.0f}")
    if note:
        lines.append(f"- _{note}_")
    cache = bundle.get("cache") or {}
    if isinstance(cache, dict) and cache.get("hit"):
        lines.append("- _Served from cache (TTL applies)._")
    qrows = bundle.get("queries") or []
    if isinstance(qrows, list) and qrows:
        lines.append("\n**Sources (snippets):**")
        for block in qrows[:6]:
            if not isinstance(block, dict):
                continue
            q = (block.get("query") or "")[:120]
            if q:
                lines.append(f"- _{q}_")
            for r in (block.get("results") or [])[:2]:
                if not isinstance(r, dict):
                    continue
                title = (r.get("title") or "")[:200]
                url = r.get("url") or ""
                if title:
                    lines.append(f"  - [{title}]({url})" if url else f"  - {title}")
    return "\n".join(lines).strip()


def _read_cache() -> dict[str, Any] | None:
    if not _CACHE_FILE.is_file():
        return None
    try:
        raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _write_cache(payload: dict[str, Any]) -> None:
    try:
        _VAR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _cache_fresh(cached: dict[str, Any], *, ttl_sec: int) -> bool:
    ts = cached.get("fetched_at_unix")
    if not isinstance(ts, (int, float)):
        return False
    return (time.time() - float(ts)) < float(ttl_sec)


def solar_project_progress_pct(*, organization_id: int) -> int:
    """Persisted progress bar (operator-editable JSON) with safe bounds."""
    oid = int(organization_id)
    path = _ROOT / "var" / f"solar_project_progress_org_{oid}.json"
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                p = data.get("progress_pct")
                if isinstance(p, (int, float)):
                    return max(0, min(100, int(round(float(p)))))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return DEFAULT_SOLAR_PROGRESS_PCT if oid == int(MASS_SUCCESS_AGRO_AGENCY_ID) else 0


def fetch_solar_dpr_research_bundle(*, force_refresh: bool = False, ttl_sec: int | None = None) -> dict[str, Any]:
    """
    Run Tavily (or return cache). Returns inner bundle without schema wrapper.
    """
    ttl = int(ttl_sec if ttl_sec is not None else DEFAULT_CACHE_TTL_SEC)
    if not force_refresh:
        hit = _read_cache()
        if hit is not None and _cache_fresh(hit, ttl_sec=ttl):
            hit = dict(hit)
            hit["cache"] = {"hit": True, "ttl_seconds": ttl}
            return hit

    bundle = _run_all_tavily_queries()
    bundle["fetched_at_unix"] = time.time()
    bundle["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
    bundle["cache"] = {"hit": False, "ttl_seconds": ttl}
    to_store = dict(bundle)
    to_store.pop("cache", None)
    _write_cache(to_store)
    return bundle


def build_solar_dpr_dashboard_block(
    *,
    organization_id: int,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    JSON block for ``GET /analytics/master-dashboard`` when the tenant is the Solar DPR org.

    Schema ``thiramai.solar_dpr_market_research.v1``.
    """
    oid = int(organization_id)
    if oid != int(MASS_SUCCESS_AGRO_AGENCY_ID):
        return {"schema": "thiramai.solar_dpr_market_research.v1", "applicable": False}

    bundle = fetch_solar_dpr_research_bundle(force_refresh=force_refresh)
    cache = bundle.get("cache") or {}
    progress = solar_project_progress_pct(organization_id=oid)
    return {
        "schema": "thiramai.solar_dpr_market_research.v1",
        "applicable": True,
        "organization_id": oid,
        "project": {
            "name": "Solar Panel Manufacturing — DPR track",
            "phase_progress_pct": progress,
            "phase_label": "Market research & capex framing",
        },
        "initial_capex_estimate_inr": bundle.get("initial_capex_estimate_inr"),
        "initial_capex_low_inr": bundle.get("initial_capex_low_inr"),
        "initial_capex_high_inr": bundle.get("initial_capex_high_inr"),
        "initial_capex_note": bundle.get("initial_capex_note"),
        "market_research": {
            "queries": bundle.get("queries") or [],
            "fetched_at_utc": bundle.get("fetched_at_utc"),
        },
        "cache": cache,
    }


if __name__ == "__main__":
    # Trigger Tavily DPR pull (writes ``var/solar_dpr_tavily_cache.json``). Usage: ``python -m services.market_research_service [--force]``
    import sys

    from core.env_bootstrap import load_project_dotenv

    load_project_dotenv()
    force = "--force" in sys.argv
    out = fetch_solar_dpr_research_bundle(force_refresh=force)
    print(json.dumps(out, indent=2, ensure_ascii=False))
