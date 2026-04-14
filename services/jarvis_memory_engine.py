"""
Living Jarvis — Upgrade 1: context memory (episodic, semantic, working memory).

Persists across sessions: episodes and facts in PostgreSQL/SQLite; optional ``pgvector``
can be wired later via ``embedding`` JSON arrays and ``<=>`` queries — current ``recall``
uses token overlap + importance when vectors are absent.
"""

from __future__ import annotations

import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import JarvisEpisode, JarvisFact, JarvisSession, JarvisSessionTurn

_log = logging.getLogger("thiramai.jarvis_memory_engine")

_MAX_CONTENT = 12000
_MAX_TITLE = 512
_MAX_TURN = 8000


def _tokenize(text_in: str) -> set[str]:
    return {t for t in re.findall(r"[\w\u0080-\uffff]+", (text_in or "").lower()) if len(t) > 1}


def _score_overlap(query_tokens: set[str], doc: str, *, importance: int) -> float:
    if not query_tokens:
        return float(importance) * 0.01
    doc_tokens = _tokenize(doc)
    if not doc_tokens:
        return 0.0
    inter = len(query_tokens & doc_tokens)
    return inter + min(importance, 10) * 0.15


def _default_expires_at(importance: int, created: datetime) -> datetime | None:
    if importance >= 8:
        return None
    return created + timedelta(days=90)


def _auto_importance(user_text: str, assistant_text: str) -> int:
    blob = f"{user_text} {assistant_text}".lower()
    score = 5
    if any(w in blob for w in ("critical", "important", "never forget", "must remember", "do not forget")):
        score += 3
    if any(w in blob for w in ("idea", "milestone", "launch", "investor", "order worth")):
        score += 2
    if len(user_text) > 400:
        score += 1
    return max(1, min(10, score))


class JarvisMemoryEngine:
    """Episodic + semantic + session working memory for Jarvis."""

    def store_episode(
        self,
        user_id: int,
        episode_type: str,
        content: str,
        importance: int = 5,
        *,
        title: str | None = None,
        embedding: list[float] | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        uid = int(user_id)
        if uid <= 0:
            return {"ok": False, "error": "invalid user_id"}
        et = (episode_type or "note").strip()[:64]
        body = (content or "").strip()[:_MAX_CONTENT]
        if not body:
            return {"ok": False, "error": "content required"}
        imp = max(1, min(10, int(importance)))
        ttl = (title or body.split("\n", 1)[0]).strip()[:_MAX_TITLE]
        factory = get_session_factory()
        if factory is None:
            return {"ok": False, "error": "database not configured"}
        now = datetime.now(timezone.utc)
        exp = expires_at if expires_at is not None else _default_expires_at(imp, now)
        try:
            with factory() as session:
                with session.begin():
                    row = JarvisEpisode(
                        user_id=uid,
                        episode_type=et,
                        title=ttl,
                        content=body,
                        importance=imp,
                        embedding=embedding,
                        created_at=now,
                        expires_at=exp,
                    )
                    session.add(row)
                    session.flush()
                    eid = int(row.id)
            return {"ok": True, "id": eid}
        except Exception as exc:
            _log.warning("store_episode failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def store_fact(
        self,
        user_id: int,
        fact_type: str,
        key: str,
        value: str,
        source: str,
        *,
        confidence: float = 0.7,
    ) -> dict[str, Any]:
        uid = int(user_id)
        if uid <= 0:
            return {"ok": False, "error": "invalid user_id"}
        ft = (fact_type or "general").strip()[:64]
        k = (key or "").strip()[:256]
        v = (value or "").strip()[:_MAX_CONTENT]
        src = (source or "jarvis").strip()[:64]
        if not k or not v:
            return {"ok": False, "error": "key and value required"}
        factory = get_session_factory()
        if factory is None:
            return {"ok": False, "error": "database not configured"}
        conf = Decimal(str(confidence)).quantize(Decimal("0.01"))
        now = datetime.now(timezone.utc)
        try:
            with factory() as session:
                with session.begin():
                    existing = session.execute(
                        select(JarvisFact).where(
                            JarvisFact.user_id == uid,
                            JarvisFact.fact_type == ft,
                            JarvisFact.key == k,
                        ).limit(1)
                    ).scalar_one_or_none()
                    if existing:
                        existing.value = v
                        existing.confidence = conf
                        existing.source = src
                        existing.last_verified = now
                    else:
                        session.add(
                            JarvisFact(
                                user_id=uid,
                                fact_type=ft,
                                key=k,
                                value=v,
                                confidence=conf,
                                source=src,
                                last_verified=now,
                            )
                        )
            return {"ok": True}
        except Exception as exc:
            _log.warning("store_fact failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def get_session_context(
        self,
        user_id: int,
        session_id: str,
        last_n: int = 10,
        *,
        recall_query: str | None = None,
    ) -> dict[str, Any]:
        uid = int(user_id)
        sid = (session_id or "default").strip()[:128] or "default"
        n = max(1, min(int(last_n), 40))
        factory = get_session_factory()
        if factory is None or uid <= 0:
            return {"session_key": sid, "turns": [], "recalled": []}
        rq = (recall_query or "").strip()
        recalled = self.recall(uid, rq, top_k=5) if rq else []
        with factory() as session:
            sess = session.execute(
                select(JarvisSession).where(JarvisSession.user_id == uid, JarvisSession.session_id == sid).limit(1)
            ).scalar_one_or_none()
            if sess is None:
                rows: list[JarvisSessionTurn] = []
            else:
                turns_q = (
                    select(JarvisSessionTurn)
                    .where(JarvisSessionTurn.session_row_id == sess.id)
                    .order_by(JarvisSessionTurn.created_at.desc())
                    .limit(n)
                )
                rows = list(session.scalars(turns_q).all())
        rows.reverse()
        turns_out = [{"role": r.role, "content": r.content[:_MAX_TURN], "at": r.created_at.isoformat()} for r in rows]
        return {"session_key": sid, "turns": turns_out, "recalled": recalled}

    def recall(self, user_id: int, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        uid = int(user_id)
        q = (query or "").strip()
        k = max(1, min(int(top_k), 20))
        if uid <= 0 or not q:
            return []
        q_tokens = _tokenize(q)
        factory = get_session_factory()
        if factory is None:
            return []
        now = datetime.now(timezone.utc)
        scored: list[tuple[float, dict[str, Any]]] = []
        with factory() as session:
            ep_stmt = (
                select(JarvisEpisode)
                .where(JarvisEpisode.user_id == uid)
                .where((JarvisEpisode.expires_at.is_(None)) | (JarvisEpisode.expires_at > now))
                .order_by(JarvisEpisode.created_at.desc())
                .limit(200)
            )
            for ep in session.scalars(ep_stmt).all():
                doc = f"{ep.title}\n{ep.content}"
                base = _score_overlap(q_tokens, doc, importance=int(ep.importance or 5))
                emb_bonus = 0.0
                if ep.embedding and isinstance(ep.embedding, list) and len(ep.embedding) > 8:
                    emb_bonus = _embedding_bonus(q_tokens, ep.embedding)
                scored.append((base + emb_bonus, self._episode_hit(ep)))
            fact_stmt = select(JarvisFact).where(JarvisFact.user_id == uid).order_by(JarvisFact.created_at.desc()).limit(150)
            for f in session.scalars(fact_stmt).all():
                doc = f"{f.fact_type} {f.key} {f.value}"
                sc = _score_overlap(q_tokens, doc, importance=int(float(f.confidence or 0.5) * 10))
                scored.append((sc, self._fact_hit(f)))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = [h for sc, h in scored if sc > 0.01][:k]
        return out

    def summarize_old_memories(self, user_id: int, older_than_days: int = 30) -> dict[str, Any]:
        uid = int(user_id)
        if uid <= 0:
            return {"ok": False, "error": "invalid user_id"}
        days = max(7, min(int(older_than_days), 365))
        factory = get_session_factory()
        if factory is None:
            return {"ok": False, "error": "database not configured"}
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        key = (os.getenv("GROQ_API_KEY") or "").strip()
        with factory() as session:
            rows = list(
                session.scalars(
                    select(JarvisEpisode)
                    .where(
                        JarvisEpisode.user_id == uid,
                        JarvisEpisode.created_at < cutoff,
                        JarvisEpisode.importance < 9,
                        JarvisEpisode.episode_type != "memory_archive_summary",
                    )
                    .order_by(JarvisEpisode.created_at.asc())
                    .limit(80)
                ).all()
            )
        if not rows:
            return {"ok": True, "merged": 0, "detail": "nothing to summarize"}
        episode_ids = [int(r.id) for r in rows]
        bundle = "\n\n---\n\n".join(f"[{r.episode_type}] {r.title}\n{r.content[:800]}" for r in rows)
        summary_text = ""
        if key and len(bundle) > 50:
            summary_text = _groq_summarize_episodes(bundle[:12000])
        if not summary_text:
            summary_text = "Archived memories (auto-summary skipped): " + "; ".join((r.title or "")[:80] for r in rows[:12])
        try:
            with factory() as session:
                with session.begin():
                    session.execute(delete(JarvisEpisode).where(JarvisEpisode.id.in_(episode_ids)))
                    session.add(
                        JarvisEpisode(
                            user_id=uid,
                            episode_type="memory_archive_summary",
                            title=f"Compressed memories before {cutoff.date().isoformat()}",
                            content=summary_text[:_MAX_CONTENT],
                            importance=7,
                            created_at=datetime.now(timezone.utc),
                            expires_at=None,
                        )
                    )
            return {"ok": True, "merged": len(rows)}
        except Exception as exc:
            _log.warning("summarize_old_memories failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    # --- Prompt + turn recording (Jarvis agent integration) ---

    def format_memory_context_block(
        self,
        *,
        user_id: int,
        session_id: str | None,
        current_user_message: str,
        last_n: int = 10,
        top_k: int = 5,
    ) -> str:
        """Human-readable block for the system prompt."""
        ctx = self.get_session_context(
            user_id,
            session_id or "default",
            last_n=last_n,
            recall_query=current_user_message,
        )
        lines: list[str] = ["MEMORY CONTEXT:"]
        if ctx["turns"]:
            lines.append("Working memory (recent turns):")
            for t in ctx["turns"][-last_n:]:
                role = t.get("role") or "?"
                content = (t.get("content") or "")[:600]
                lines.append(f"- ({role}) {content}")
        else:
            lines.append("Working memory: (no prior turns in this session)")
        lines.append("Retrieved long-term memory (episodes + facts):")
        recalled = ctx.get("recalled") or []
        if not recalled:
            lines.append("- (none strongly matching this query — answer from context and tools)")
        for h in recalled:
            imp = h.get("importance") or h.get("confidence")
            src = h.get("source", "memory")
            lines.append(f"- [{src}] {h.get('summary', '')} (relevance: {imp})")
        lines.append(
            "Use this context to personalize responses. If something conflicts with live tool data, prefer tools."
        )
        return "\n".join(lines)

    def record_conversation_turn(
        self,
        *,
        user_id: int,
        session_id: str | None,
        user_message: str,
        assistant_message: str,
        episode_type: str = "conversation",
        tool_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append session turns, episodic row, and delegate preference extraction to jarvis_memory_learn."""
        uid = int(user_id)
        sid = (session_id or "default").strip()[:128] or "default"
        um = (user_message or "").strip()[:_MAX_TURN]
        am = (assistant_message or "").strip()[:_MAX_TURN]
        if uid <= 0 or not um:
            return {"ok": False, "error": "invalid turn"}
        factory = get_session_factory()
        if factory is None:
            return {"ok": False, "error": "database not configured"}
        imp = _auto_importance(um, am)
        try:
            with factory() as session:
                with session.begin():
                    sess = self._get_or_create_session_row(session, uid, sid)
                    session.add(JarvisSessionTurn(session_row_id=sess.id, role="user", content=um))
                    if am:
                        session.add(JarvisSessionTurn(session_row_id=sess.id, role="assistant", content=am))
                    sess.message_count = int(sess.message_count or 0) + (2 if am else 1)
                    sess.last_active = datetime.now(timezone.utc)
                    ep = JarvisEpisode(
                        user_id=uid,
                        episode_type=(episode_type or "conversation").strip()[:64],
                        title=um.split("\n", 1)[0][:240],
                        content=f"User:\n{um}\n\nAssistant:\n{am}"[:_MAX_CONTENT],
                        importance=imp,
                        created_at=datetime.now(timezone.utc),
                        expires_at=_default_expires_at(imp, datetime.now(timezone.utc)),
                    )
                    session.add(ep)
        except Exception as exc:
            _log.warning("record_conversation_turn failed: %s", exc)
            return {"ok": False, "error": str(exc)}

        if tool_results:
            for tr in tool_results[:6]:
                if not isinstance(tr, dict):
                    continue
                tname = str(tr.get("tool") or "")
                res = tr.get("result")
                if isinstance(res, dict) and res.get("ok") and tname in (
                    "create_task",
                    "record_sale",
                    "add_stock",
                    "create_invoice",
                ):
                    self.store_fact(
                        uid,
                        "tool_habit",
                        f"used_{tname}",
                        f"User successfully ran {tname} via Jarvis.",
                        "post_turn",
                        confidence=0.35,
                    )
        return {"ok": True}

    def _get_or_create_session_row(self, session: Session, user_id: int, client_key: str) -> JarvisSession:
        stmt = select(JarvisSession).where(
            JarvisSession.user_id == user_id,
            JarvisSession.session_id == client_key,
        )
        row = session.execute(stmt.limit(1)).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row:
            row.last_active = now
            return row
        row = JarvisSession(user_id=user_id, session_id=client_key, started_at=now, last_active=now, message_count=0)
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def _episode_hit(ep: JarvisEpisode) -> dict[str, Any]:
        return {
            "source": "episode",
            "episode_type": ep.episode_type,
            "summary": f"{(ep.title or '')[:120]} — {(ep.content or '')[:200]}",
            "importance": int(ep.importance or 5),
            "created_at": ep.created_at.isoformat() if ep.created_at else None,
        }

    @staticmethod
    def _fact_hit(f: JarvisFact) -> dict[str, Any]:
        return {
            "source": "fact",
            "summary": f"{f.fact_type}.{f.key} = {(f.value or '')[:200]}",
            "confidence": float(f.confidence or 0),
        }


def _embedding_bonus(query_tokens: set[str], embedding: list[Any]) -> float:
    """Tiny cosine-like signal when query tokens are hashed into a bag-of-words pseudo-vector."""
    try:
        vec = [float(x) for x in embedding if isinstance(x, (int, float))]
        if len(vec) < 8:
            return 0.0
    except (TypeError, ValueError):
        return 0.0
    dim = min(len(vec), 64)
    v = vec[:dim]
    q = [0.0] * dim
    for i, t in enumerate(sorted(query_tokens)[: dim // 2]):
        h = hash(t) % dim
        q[h] += 1.0
    dot = sum(a * b for a, b in zip(q, v))
    na = math.sqrt(sum(x * x for x in q))
    nb = math.sqrt(sum(x * x for x in v))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    sim = max(0.0, min(1.0, dot / (na * nb)))
    return sim * 0.5


def _groq_summarize_episodes(blob: str) -> str:
    try:
        from groq import Groq

        model = (os.getenv("GROQ_FAST_MODEL") or "llama-3.1-8b-instant").strip()
        client = Groq(api_key=os.getenv("GROQ_API_KEY", "").strip())
        chat = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize the following user memory episodes into one concise paragraph "
                        "(facts, preferences, open decisions). No bullet list longer than 6 items.\n\n" + blob
                    ),
                }
            ],
            temperature=0.2,
            max_tokens=512,
        )
        return (chat.choices[0].message.content or "").strip()[:8000]
    except Exception as exc:
        _log.debug("groq summarize episodes skipped: %s", exc)
        return ""


_engine_singleton: JarvisMemoryEngine | None = None


def get_default_engine() -> JarvisMemoryEngine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = JarvisMemoryEngine()
    return _engine_singleton


def fetch_living_memory_brief_sync(user_id: int, *, episode_limit: int = 4) -> dict[str, Any]:
    """Lightweight snippet for Today / personal payload (recent episodic memory)."""
    uid = int(user_id)
    if uid <= 0:
        return {}
    factory = get_session_factory()
    if factory is None:
        return {}
    lim = max(1, min(int(episode_limit), 12))
    try:
        with factory() as session:
            rows = list(
                session.scalars(
                    select(JarvisEpisode)
                    .where(JarvisEpisode.user_id == uid)
                    .order_by(JarvisEpisode.created_at.desc())
                    .limit(lim)
                ).all()
            )
    except Exception as exc:
        _log.debug("fetch_living_memory_brief skipped: %s", exc)
        return {}
    return {
        "recent_episodes": [
            {
                "title": (r.title or "")[:200],
                "type": r.episode_type,
                "importance": int(r.importance or 5),
                "when": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
