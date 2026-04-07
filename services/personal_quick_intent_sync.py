"""
Map short spoken-style phrases to ``execute_personal_action_sync`` payloads (optional Jarvis input).
"""

from __future__ import annotations

import re
from typing import Any


def parse_quick_phrase(phrase: str) -> dict[str, Any]:
    """
    Returns ``{"ok": True, "action": str, "item": ..., "title": ..., "quantity": ...}``
    or ``{"ok": False, "error": str}``.
    """
    p = (phrase or "").strip()
    p = re.sub(r"^\s*hey\s*,?\s*thiramai\s*[,.!]?\s*", "", p, flags=re.I).strip()
    if not p:
        return {"ok": False, "error": "empty phrase"}

    low = p.lower()

    m = re.match(r"^(?:add|create)\s+task\s+(.+)$", low, re.I)
    if m:
        title = m.group(1).strip().strip('"').strip("'")
        if not title:
            return {"ok": False, "error": "task title missing"}
        return {"ok": True, "action": "add_task", "title": title}

    m = re.match(r"^(?:restock|add\s+stock)\s+(.+)$", low, re.I)
    if m:
        sku = m.group(1).strip().strip('"').strip("'")
        if not sku:
            return {"ok": False, "error": "item name missing"}
        return {"ok": True, "action": "restock", "item": sku}

    m = re.match(r"^(?:log|record)\s+(?:a\s+)?sale\b", low, re.I)
    if m:
        return {"ok": True, "action": "record_sale"}

    m = re.match(
        r"^(?:research\s+(?:feedback|correction)|correct\s+research|dpr\s+feedback)\s*[:\-]?\s*(.+)$",
        p,
        re.I | re.DOTALL,
    )
    if m:
        fb = m.group(1).strip().strip('"').strip("'")
        if not fb:
            return {"ok": False, "error": "research feedback text missing"}
        return {"ok": True, "action": "research_feedback", "feedback": fb}

    return {"ok": False, "error": "could not map phrase; try e.g. 'add task buy stock'"}
