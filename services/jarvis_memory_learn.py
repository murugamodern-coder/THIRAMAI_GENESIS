"""Post-turn learning: extract simple preferences from user text and optional Groq JSON."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from services.jarvis_memory_service import upsert_memory_sync

_log = logging.getLogger("thiramai.jarvis_memory_learn")

_PREFER = re.compile(
    r"\b(?:i\s+prefer|i\s+always|i\s+usually|default\s+(?:to\s+)?|prefer\s+(?:using\s+)?)\s+([^\.!\n]{3,120})",
    re.I,
)
_PAYMENT = re.compile(r"\b(upi|cash|bank\s+transfer|neft|imps)\b", re.I)
_LANG = re.compile(r"\b(reply|respond|answer)\s+in\s+(tamil|english)\b", re.I)


def learn_from_turn_sync(
    *,
    user_id: int,
    user_message: str,
    assistant_text: str,
    tool_results: list[dict[str, Any]] | None = None,
) -> list[str]:
    """
    Heuristic + optional LLM extraction. Returns memory keys touched.
    """
    uid = int(user_id)
    if uid <= 0:
        return []
    touched: list[str] = []
    um = (user_message or "").strip()
    if not um:
        return []

    m = _PREFER.search(um)
    if m:
        val = m.group(1).strip()
        if len(val) > 3:
            r = upsert_memory_sync(user_id=uid, memory_key="preference", memory_value=val[:400], confidence=0.55)
            if r.get("ok"):
                touched.append("preference")

    pm = _PAYMENT.search(um)
    if pm:
        r = upsert_memory_sync(
            user_id=uid,
            memory_key="payment_preference",
            memory_value=f"User mentioned {pm.group(1)}",
            confidence=0.5,
        )
        if r.get("ok"):
            touched.append("payment_preference")

    lm = _LANG.search(um)
    if lm:
        r = upsert_memory_sync(
            user_id=uid,
            memory_key="language_preference",
            memory_value=lm.group(2).lower(),
            confidence=0.55,
        )
        if r.get("ok"):
            touched.append("language_preference")

    # Repeated tool patterns (same tool 3+ times in session not tracked here — optional future)

    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if key and len(um) > 20 and _should_llm_extract(um):
        extra = _groq_extract_memories(uid, um, assistant_text)
        touched.extend(extra)

    if tool_results:
        for tr in tool_results[:8]:
            if not isinstance(tr, dict):
                continue
            tname = str(tr.get("tool") or "")
            res = tr.get("result")
            if tname == "add_business_expense" and isinstance(res, dict) and res.get("ok"):
                cat = ((res.get("message") or "") + str(tr)).lower()
                if "emi" in cat or "rent" in cat:
                    upsert_memory_sync(
                        user_id=uid,
                        memory_key="recent_expense_category",
                        memory_value=f"Logged business expense via Jarvis ({tname})",
                        confidence=0.35,
                    )
                    touched.append("recent_expense_category")

    return list(dict.fromkeys(touched))


def _should_llm_extract(um: str) -> bool:
    return any(
        x in um.lower()
        for x in ("remember", "note that", "don't forget", "from now on", "always use", "my supplier", "my default")
    )


def _groq_extract_memories(user_id: int, user_message: str, assistant_text: str) -> list[str]:
    try:
        from groq import Groq

        model = (os.getenv("GROQ_FAST_MODEL") or "llama-3.1-8b-instant").strip()
        client = Groq(api_key=os.getenv("GROQ_API_KEY", "").strip())
        prompt = (
            "Extract 0 to 2 durable user-specific facts for a business assistant memory store.\n"
            'Return ONLY valid JSON: {"memories":[{"key":"short_snake_case","value":"plain text"}]}\n'
            f"User said:\n{user_message[:2000]}\n"
            f"Assistant said (truncated):\n{(assistant_text or '')[:800]}\n"
        )
        chat = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=256,
        )
        raw = (chat.choices[0].message.content or "").strip()
        if not raw:
            return []
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return []
        data = json.loads(raw[start : end + 1])
        mems = data.get("memories") if isinstance(data, dict) else None
        if not isinstance(mems, list):
            return []
        touched: list[str] = []
        for item in mems[:2]:
            if not isinstance(item, dict):
                continue
            k = str(item.get("key") or "").strip()[:128]
            v = str(item.get("value") or "").strip()[:2000]
            if not k or not v:
                continue
            r = upsert_memory_sync(user_id=user_id, memory_key=k, memory_value=v, confidence=0.45)
            if r.get("ok"):
                touched.append(k)
        return touched
    except Exception as exc:
        _log.debug("groq memory extract skipped: %s", exc)
        return []
