"""Clamp and strip dangerous keys from tool arguments before execution."""

from __future__ import annotations

import copy
from typing import Any

_MAX_STR = 8000
_MAX_DEPTH = 8
_MAX_KEYS = 80


def sanitize_tool_arguments(tool_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    out = copy.deepcopy(args)
    _ = tool_name
    _scrub(out, depth=0, key_count=0)
    return out


def _scrub(obj: Any, *, depth: int, key_count: int) -> int:
    if depth > _MAX_DEPTH:
        return key_count
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            key_count += 1
            if key_count > _MAX_KEYS:
                obj.clear()
                return key_count
            sk = str(k)
            if sk.startswith("__") or sk.startswith("system_") or sk.startswith("assistant_"):
                obj.pop(k, None)
                continue
            v = obj[k]
            if isinstance(v, str):
                obj[k] = v[:_MAX_STR]
            else:
                key_count = _scrub(v, depth=depth + 1, key_count=key_count)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:80]):
            if isinstance(v, str):
                obj[i] = v[:_MAX_STR]
            else:
                key_count = _scrub(v, depth=depth + 1, key_count=key_count)
    return key_count
