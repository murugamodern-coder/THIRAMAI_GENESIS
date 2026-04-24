"""
Scientific validation: multi-source cross-check, source credibility, contradictions, uncertainty flags.
Intended to harden research outputs; not a substitute for human expert review.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from services.research_common import groq_json_object_sync, tavily_search_sync
from services.research_engine_service import run_supplier_research_sync

# Government / established patterns (India + general)
_GOV_PAT = re.compile(r"\.(gov|nic)\.(in|co\.in)\b|gov\.in/|wikipedia\.org|scholar\.|arxiv\.|nature\.com|reuters\.|ndtv\.|thehindu\.", re.I)
_EDU_PAT = re.compile(r"\.edu\b|ac\.in\b|iit|iisc|icar\.", re.I)
_NEWS_PAT = re.compile(r"bbc\.|economist\.|ft\.com|wsj\.|bloomberg\.", re.I)
_LOW_TRUST = re.compile(
    r"blogspot\.|wordpress\.com|tumblr\.|medium\.com/@[^/]+/|(?:^|\.)rumor|conspiracy|"
    r"clickbait|free-?article|adult|casino|pharma-?deals-?now",
    re.I,
)
_LLM_CONTRADICT_SYSTEM = """You are a research reliability analyst. Given two text blocks (primary and cross-check) and a topic, return STRICT JSON:
{
  "contradictions": [
    {"aspect": "short label", "primary_says": "paraphrase or quote", "crosscheck_says": "paraphrase or quote", "severity": "low|medium|high"}
  ],
  "uncertain_aspects": ["short strings"],
  "reliability_comment": "one or two sentences; empty string if nothing to add"
}
Rules: Only use provided text. If nothing conflicts, use empty arrays. Do not invent facts."""


def score_source_credibility(url: str) -> dict[str, Any]:
    u = (url or "").strip()
    if not u or not u.startswith("http"):
        return {"url": u, "score_0_1": 0.35, "tier": "unknown", "reasons": ["Missing or non-HTTP URL"]}
    host = (urlparse(u).netloc or "").lower()
    reasons: list[str] = []
    base = 0.45
    if _LOW_TRUST.search(u) or _LOW_TRUST.search(host):
        base = 0.25
        reasons.append("Host pattern associated with low verification")
    if _GOV_PAT.search(u):
        base = min(0.95, base + 0.35)
        reasons.append("Government or high-trust reference domain")
    if _EDU_PAT.search(u):
        base = min(0.9, base + 0.22)
        reasons.append("Academic / .edu or India academic")
    if _NEWS_PAT.search(u):
        base = min(0.88, base + 0.18)
        reasons.append("Major news wire")
    if "linkedin.com" in host or "facebook.com" in host:
        base = min(base, 0.55)
        reasons.append("Social UGC; verify independently")
    if not reasons:
        reasons.append("Generic web source; corroborate")
    score = max(0.1, min(0.98, base))
    tier = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    return {"url": u[:2000], "score_0_1": round(score, 3), "tier": tier, "host": host[:200], "reasons": reasons[:4]}


def _tavily_row_score(row: dict[str, Any]) -> float:
    s = row.get("score")
    if s is not None:
        try:
            return max(0.0, min(1.0, float(s)))
        except (TypeError, ValueError):
            pass
    u = str(row.get("url") or "")
    return float(score_source_credibility(u).get("score_0_1") or 0.5)


def _token_set(text: str) -> set[str]:
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return {w for w in t.split() if len(w) > 2} - {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "are",
        "was",
        "has",
        "have",
        "not",
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / max(union, 1)


def _extract_numbers(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for m in re.finditer(r"(₹|rs\.?|inr|rupees?)\s*[\d,]+(?:\.\d+)?|(?:^|\s)[\d,]+(?:\.\d+)?\s*%", text or "", re.I):
        raw = m.group(0)
        n = re.sub(r"[^\d.]", "", raw.replace(",", ""))
        try:
            v = float(n)
            if v > 0:
                out.append((raw.strip()[:40], v))
        except ValueError:
            continue
    return out[:12]


def _heuristic_contradictions(text_a: str, text_b: str) -> list[dict[str, Any]]:
    a, b = (text_a or ""), (text_b or "")
    issues: list[dict[str, Any]] = []
    neg = re.compile(r"\b(no|not|never|declin|decreas|fall|drop|reduc|loss|weak|unsuccess)\b", re.I)
    pos = re.compile(r"\b(yes|growth|increas|rise|strong|success|expand|profit|surge)\b", re.I)
    if neg.search(a) and pos.search(b) and _jaccard(_token_set(a[:800]), _token_set(b[:800])) > 0.08:
        issues.append(
            {
                "aspect": "sentiment_or_direction",
                "primary_says": "Contains negative/decline language",
                "crosscheck_says": "Contains positive/growth language (review context)",
                "severity": "medium",
                "source": "heuristic",
            }
        )
    nums_a = _extract_numbers(a)
    nums_b = _extract_numbers(b)
    for la, va in nums_a:
        for lb, vb in nums_b:
            if va <= 0 or vb <= 0:
                continue
            r = max(va, vb) / min(va, vb)
            if r >= 4.0 and min(va, vb) > 10:
                issues.append(
                    {
                        "aspect": "numeric_mismatch",
                        "primary_says": la,
                        "crosscheck_says": lb,
                        "severity": "high" if r >= 10 else "medium",
                        "source": "heuristic",
                    }
                )
                break
    return issues


def _llm_contradictions(topic: str, block_a: str, block_b: str) -> dict[str, Any] | None:
    if not (block_a or "").strip() or not (block_b or "").strip():
        return None
    return groq_json_object_sync(
        system=_LLM_CONTRADICT_SYSTEM,
        user_content=f"Topic: {topic[:500]}\n\nPRIMARY:\n{block_a[:8000]}\n\nCROSS-CHECK:\n{block_b[:8000]}",
        max_tokens=1200,
    )


def _merge_contradictions(
    heur: list[dict[str, Any]], llm: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], list[str], str]:
    extra = (llm or {}).get("contradictions") if isinstance(llm, dict) else None
    uncer = (llm or {}).get("uncertain_aspects") if isinstance(llm, dict) else None
    note = str((llm or {}).get("reliability_comment") or "") if isinstance(llm, dict) else ""
    out = list(heur)
    if isinstance(extra, list):
        for e in extra[:8]:
            if not isinstance(e, dict):
                continue
            out.append(
                {
                    "aspect": str(e.get("aspect") or "claim"),
                    "primary_says": str(e.get("primary_says") or ""),
                    "crosscheck_says": str(e.get("cross_says") or e.get("crosscheck_says") or ""),
                    "severity": str(e.get("severity") or "low"),
                    "source": "llm",
                }
            )
    u2: list[str] = [str(x) for x in (uncer or []) if str(x).strip()][:8]
    return out, u2, note


def _aggregate_reliability(
    *,
    source_scores: list[float],
    jacc: float,
    n_contra: int,
    high_contra: int,
    uncertain: list[str],
) -> tuple[float, list[str]]:
    flags: list[str] = []
    avg = sum(source_scores) / max(len(source_scores), 1) if source_scores else 0.4
    rel = 0.35 * avg + 0.4 * (0.15 + 0.85 * jacc) + 0.25 * (1.0 if n_contra == 0 else max(0.2, 0.9 - 0.12 * n_contra - 0.2 * high_contra))
    if jacc < 0.12:
        flags.append("low_semantic_alignment_between_sources")
    if avg < 0.45:
        flags.append("weak_average_source_credibility")
    if n_contra > 0:
        flags.append("potential_contradictions_detected")
    if high_contra:
        flags.append("high_severity_numeric_or_claim_conflict")
    if uncertain:
        flags.append("model_flagged_uncertain_aspects")
    if rel < 0.5:
        flags.append("treat_conclusions_as_preliminary")
    return max(0.05, min(0.99, rel)), flags


def multi_source_validate(
    query: str,
    *,
    cross_query: str | None = None,
    max_results_primary: int = 12,
    max_results_cross: int = 10,
    use_llm: bool = True,
) -> dict[str, Any]:
    """
    Run primary supplier research, independent Tavily cross-check, score sources, find conflicts, flag uncertainty.
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}
    primary = run_supplier_research_sync(q, max_results=max(5, int(max_results_primary)))
    psum = str((primary or {}).get("summary") or "")
    plinks = [str(x) for x in ((primary or {}).get("links") or []) if x][:20]
    cq = (cross_query or f"independent verification facts news {q}")[:400]
    raw2 = tavily_search_sync(cq, max_results=max(3, int(max_results_cross)))
    results2: list[dict[str, Any]] = []
    cross_blob = ""
    if isinstance(raw2, dict) and raw2.get("ok") is not False and not raw2.get("error"):
        results2 = [r for r in (raw2.get("results") or []) if isinstance(r, dict)][:20]
        parts = []
        for r in results2:
            t = str(r.get("title") or "")[:200]
            b = str(r.get("content") or r.get("snippet") or "")[:900]
            uu = str(r.get("url") or "")
            parts.append(f"{t}\n{uu}\n{b}")
        cross_blob = "\n---\n".join(parts)[:12000]
    else:
        cross_blob = f"(Cross-check search unavailable: { (raw2 or {}).get('error', 'no data') })"

    scored: list[dict[str, Any]] = []
    for u in plinks:
        scored.append(score_source_credibility(u))
    for r in results2:
        u = str(r.get("url") or "")
        srow = {
            "url": u,
            "score_0_1": round(_tavily_row_score(r), 3),
            "tier": "tavily_score" if r.get("score") is not None else "inferred",
            "reasons": ["Tavily result score" if r.get("score") is not None else "URL heuristics"],
        }
        scored.append(srow)

    scores = [float(x.get("score_0_1") or 0.5) for x in scored if x.get("score_0_1") is not None]
    j = _jaccard(_token_set(psum), _token_set(cross_blob))
    he = _heuristic_contradictions(psum, cross_blob)
    llm: dict[str, Any] | None = None
    if use_llm and psum and len(cross_blob) > 80 and "unavailable" not in cross_blob[:40]:
        llm = _llm_contradictions(q, psum, cross_blob)
    all_c, uncertain_llm, note = _merge_contradictions(he, llm)
    high = sum(1 for c in all_c if str(c.get("severity") or "") == "high")
    rel, flags = _aggregate_reliability(
        source_scores=scores,
        jacc=j,
        n_contra=len(all_c),
        high_contra=high,
        uncertain=uncertain_llm,
    )
    if note and (note not in " ".join(uncertain_llm)):
        uncertain_llm = [*uncertain_llm, f"llm: {note[:500]}"]

    return {
        "ok": True,
        "query": q,
        "cross_check_query": cq,
        "primary": {
            "ok": (primary or {}).get("ok"),
            "summary_excerpt": psum[:2000],
            "supplier_count": len((primary or {}).get("suppliers") or []),
            "links": plinks,
        },
        "cross_check": {
            "result_count": len(results2),
            "snippet_fingerprint": len(cross_blob),
        },
        "source_assessments": scored[:32],
        "cross_check_metrics": {
            "summary_jaccard_similarity": round(j, 4),
        },
        "contradictions": all_c,
        "uncertain_conclusions": uncertain_llm,
        "reliability_score_0_1": round(rel, 3),
        "uncertainty_flags": flags,
        "validation_summary": "Cross-source check complete; use flags and reliability for trust decisions."
        if rel >= 0.55
        else "Low agreement or weak sources; corroborate before acting.",
    }


def validate_existing_research(
    research: dict[str, Any],
    *,
    cross_text: str | None = None,
    extra_urls: list[str] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Validate an already-fetched research dict (e.g. from supplier run) with optional second body + URLs."""
    psum = str((research or {}).get("summary") or "")
    plinks = [str(x) for x in ((research or {}).get("links") or extra_urls or []) if x]
    if isinstance(research.get("suppliers"), list) and (research or {}).get("suppliers"):
        psum = psum + " " + " ".join(
            [str(s.get("name", "")) + " " + str(s.get("location", "")) for s in (research.get("suppliers") or [])[:12]]
        )
    ctext = (cross_text or "").strip() or psum
    if not ctext and not psum:
        return {"ok": False, "error": "No summary or cross_text to compare"}
    scored = [score_source_credibility(u) for u in plinks[:20]]
    scores = [float(s.get("score_0_1") or 0.5) for s in scored]
    j = _jaccard(_token_set(psum), _token_set(ctext)) if ctext != psum else 0.4
    he = _heuristic_contradictions(psum, ctext) if ctext and psum and ctext != psum else []
    llm = _llm_contradictions("corpus", psum, ctext) if use_llm and psum and ctext and ctext != psum else None
    all_c, uu, note = _merge_contradictions(he, llm)
    high = sum(1 for c in all_c if str(c.get("severity") or "") == "high")
    rel, flags = _aggregate_reliability(
        source_scores=scores,
        jacc=max(j, 0.1),
        n_contra=len(all_c),
        high_contra=high,
        uncertain=uu,
    )
    if note:
        uu = [*uu, f"llm: {note[:500]}"]
    return {
        "ok": True,
        "source_assessments": scored,
        "contradictions": all_c,
        "uncertain_conclusions": uu,
        "reliability_score_0_1": round(rel, 3),
        "uncertainty_flags": flags,
    }
