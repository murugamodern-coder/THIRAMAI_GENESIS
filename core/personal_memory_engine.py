"""
Personal context memory — learns from ``personal_suggestion_feedback`` and org ``learning_logs``
(personal feedback mirror) to bias daily guidance without new ML infrastructure.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import desc, select

from core.database import get_session_factory
from core.db.models import LearningLog, PersonalSuggestionFeedback


def _infer_action_key(text: str) -> str | None:
    t = (text or "").lower()
    if re.search(r"\brestock|re-stock|stock up|add stock\b", t):
        return "restock"
    if re.search(r"\bcomplete|task|mission\b", t):
        return "complete_task"
    if re.search(r"\bsale|pos|revenue|bill\b", t):
        return "record_sale"
    if re.search(r"\bsign in|login\b", t):
        return "sign_in"
    return None


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower()) if len(w) >= 4]


def learn_user_patterns_sync(user_id: int, organization_id: int = 0) -> dict[str, Any]:
    """
    Aggregate feedback + mirrored experiences into boost / suppress signals for ``personal_ai_engine``.

    Returns:
    - ``boost_actions`` / ``suppress_actions``: action key -> weight (int)
    - ``boost_phrases`` / ``suppress_phrases``: short substrings (deduped)
    - ``preferred_actions`` / ``ignored_actions``: sorted human lists
    - ``stats``: counts
    """
    uid = int(user_id)
    oid = int(organization_id)
    out: dict[str, Any] = {
        "boost_actions": {},
        "suppress_actions": {},
        "boost_phrases": [],
        "suppress_phrases": [],
        "preferred_actions": [],
        "ignored_actions": [],
        "stats": {"feedback_rows": 0, "experience_rows": 0},
    }
    if uid <= 0:
        return out

    factory = get_session_factory()
    if factory is None:
        return out

    fb_rows: list[PersonalSuggestionFeedback] = []
    boost_a: dict[str, int] = defaultdict(int)
    sup_a: dict[str, int] = defaultdict(int)
    boost_kw: dict[str, int] = defaultdict(int)
    sup_kw: dict[str, int] = defaultdict(int)

    with factory() as session:
        fb_rows = list(
            session.execute(
                select(PersonalSuggestionFeedback)
                .where(PersonalSuggestionFeedback.user_id == uid)
                .order_by(desc(PersonalSuggestionFeedback.created_at))
                .limit(120)
            )
            .scalars()
            .all()
        )
        out["stats"]["feedback_rows"] = len(fb_rows)
        for r in fb_rows:
            txt = (r.suggestion_text or "").strip()
            key = _infer_action_key(txt)
            toks = _tokens(txt)[:8]
            if r.helpful:
                if key:
                    boost_a[key] += 2
                for w in toks[:5]:
                    boost_kw[w] += 1
            else:
                if key:
                    sup_a[key] += 2
                for w in toks[:5]:
                    sup_kw[w] += 1
                if len(txt) >= 8:
                    sup_kw[txt[:48].lower()] += 3

        if oid > 0:
            ex_rows = list(
                session.execute(
                    select(LearningLog)
                    .where(
                        LearningLog.organization_id == oid,
                        LearningLog.action_type == "personal_suggestion_feedback",
                        LearningLog.resolved_by_user_id == uid,
                    )
                    .order_by(desc(LearningLog.created_at))
                    .limit(60)
                )
                .scalars()
                .all()
            )
            out["stats"]["experience_rows"] = len(ex_rows)
            for row in ex_rows:
                txt = (row.lesson_summary or "").strip()
                pos = (row.outcome or "").lower() in ("positive", "success", "approved")
                key = _infer_action_key(txt)
                toks = _tokens(txt)[:8]
                if pos:
                    if key:
                        boost_a[key] += 1
                    for w in toks[:4]:
                        boost_kw[w] += 1
                else:
                    if key:
                        sup_a[key] += 1
                    for w in toks[:4]:
                        sup_kw[w] += 1

    # Keep strongest signals
    out["boost_actions"] = dict(sorted(boost_a.items(), key=lambda x: -x[1])[:12])
    out["suppress_actions"] = dict(sorted(sup_a.items(), key=lambda x: -x[1])[:12])
    top_boost = sorted(boost_kw.items(), key=lambda x: -x[1])[:20]
    top_sup = sorted(sup_kw.items(), key=lambda x: -x[1])[:20]
    out["boost_phrases"] = [k for k, _ in top_boost if len(k) >= 4]
    out["suppress_phrases"] = [k for k, _ in top_sup]

    out["preferred_actions"] = list(out["boost_actions"].keys())[:8]
    out["ignored_actions"] = list(out["suppress_actions"].keys())[:8]

    helpful_n = sum(1 for r in fb_rows if r.helpful) if fb_rows else 0
    unhelpful_n = sum(1 for r in fb_rows if not r.helpful) if fb_rows else 0
    out["stats"]["helpful_n"] = helpful_n
    out["stats"]["unhelpful_n"] = unhelpful_n
    if helpful_n + unhelpful_n >= 3:
        if helpful_n >= 2 * max(1, unhelpful_n):
            out["preferred_summary"] = "You usually find nudges helpful — we'll keep them practical and short."
        elif unhelpful_n > helpful_n:
            out["preferred_summary"] = "You've marked several nudges unhelpful — we'll deprioritize similar prompts."
        else:
            out["preferred_summary"] = "Mixed feedback logged — tuning suggestions toward what you confirm helps."
    else:
        out["preferred_summary"] = "Keep using 👍/👎 on actions — the assistant learns from it."

    return out


def learn_user_patterns(user_id: int, organization_id: int = 0) -> dict[str, Any]:
    """Alias for the sync learner (spec name ``learn_user_patterns``)."""
    return learn_user_patterns_sync(user_id, organization_id)
