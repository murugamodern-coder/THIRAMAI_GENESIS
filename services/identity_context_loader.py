"""
Load a lightweight master identity context for runtime execution engines.

Sources:
- core/policies/system_v1.yaml
- core/policies/prompts_v2.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SYSTEM_V1_PATH = _ROOT / "core" / "policies" / "system_v1.yaml"
_PROMPTS_V2_PATH = _ROOT / "core" / "policies" / "prompts_v2.md"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _read_yaml(path: Path) -> dict[str, Any]:
    raw = _read_text(path)
    if not raw.strip():
        return {}
    try:
        parsed = yaml.safe_load(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_markdown_bullets(md: str, heading: str, *, limit: int = 24) -> list[str]:
    if not md.strip():
        return []
    pat = rf"(?ms)^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)"
    m = re.search(pat, md)
    if not m:
        return []
    block = m.group(1)
    lines = []
    for line in block.splitlines():
        t = line.strip()
        if t.startswith("- "):
            lines.append(t[2:].strip())
    out: list[str] = []
    for row in lines:
        if row and row not in out:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def _extract_sentences_by_keywords(text: str, keywords: list[str], *, limit: int = 6) -> list[str]:
    if not text.strip():
        return []
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    out: list[str] = []
    kws = [k.lower() for k in keywords]
    for ch in chunks:
        s = " ".join(ch.split()).strip()
        if not s:
            continue
        low = s.lower()
        if any(k in low for k in kws):
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if len(t) >= 3}


def score_long_term_alignment(command: str, identity_ctx: dict[str, Any]) -> float:
    cmd_tokens = _tokenize(command)
    if not cmd_tokens:
        return 0.0
    mission = str(identity_ctx.get("mission") or "")
    goals = list(identity_ctx.get("long_term_goals") or [])
    rules = list(identity_ctx.get("rules") or [])
    corpus = " ".join([mission] + [str(x) for x in goals] + [str(x) for x in rules])
    ctx_tokens = _tokenize(corpus)
    if not ctx_tokens:
        return 0.0
    inter = len(cmd_tokens.intersection(ctx_tokens))
    union = len(cmd_tokens.union(ctx_tokens))
    if union <= 0:
        return 0.0
    return round(max(0.0, min(1.0, inter / union)), 4)


def compute_identity_influence(
    *,
    mission_alignment_score: float,
    long_term_alignment: float,
    identity_ctx: dict[str, Any],
) -> float:
    goals = list(identity_ctx.get("long_term_goals") or [])
    rules = list(identity_ctx.get("rules") or [])
    density = min(1.0, (0.06 * len(goals)) + (0.03 * len(rules)))
    score = (0.55 * float(mission_alignment_score or 0.0)) + (0.35 * float(long_term_alignment or 0.0)) + (0.10 * density)
    return round(max(0.0, min(1.0, score)), 4)


def load_master_identity_context() -> dict[str, Any]:
    cfg = _read_yaml(_SYSTEM_V1_PATH)
    raw_yaml = _read_text(_SYSTEM_V1_PATH)
    raw_v2 = _read_text(_PROMPTS_V2_PATH)

    mission_candidates = _extract_sentences_by_keywords(
        raw_yaml + "\n" + raw_v2,
        ["mission", "purpose", "goal", "sovereign", "empire", "long-term"],
        limit=5,
    )
    rules = _extract_markdown_bullets(raw_v2, "AUTO_LEARNED_NOTES", limit=20)
    long_term_goals = _extract_sentences_by_keywords(
        raw_yaml + "\n" + raw_v2,
        ["long-term", "future", "roadmap", "space", "energy", "autonomy", "robotics", "research"],
        limit=8,
    )

    mission = mission_candidates[0] if mission_candidates else "Operate as THIRAMAI with governance-first execution and scalable long-term direction."
    if not long_term_goals:
        long_term_goals = [
            "Build stable execution capability without violating governance.",
            "Prioritize scalable actions that increase future strategic optionality.",
        ]

    master_priority = str((cfg.get("routing") or {}).get("priority_mode") or "balanced_execution")
    return {
        "identity": "THIRAMAI",
        "mission": mission,
        "rules": rules,
        "long_term_goals": long_term_goals,
        "master_priority": master_priority,
        "source_files": [str(_SYSTEM_V1_PATH), str(_PROMPTS_V2_PATH)],
        "loaded": bool(raw_yaml.strip() or raw_v2.strip()),
    }

