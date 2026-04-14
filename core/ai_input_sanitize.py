"""Reduce prompt-injection surface: strip control chars, cap length, normalize Unicode."""

from __future__ import annotations

import re
import unicodedata


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_user_text(text: str, *, max_len: int = 12_000) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _CTRL_RE.sub("", s)
    s = s.strip()
    if len(s) > max_len:
        s = s[:max_len]
    return s
