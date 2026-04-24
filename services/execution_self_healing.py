"""Error classification, fix strategies, and self-heal coordination for the action layer."""

from __future__ import annotations

import re
import time
from enum import StrEnum
from typing import Any


class ErrorClass(StrEnum):
    network = "network"
    selector = "selector"
    api = "api"
    validation = "validation"
    unknown = "unknown"


def classify_error(result: dict[str, Any] | None, step_kind: str) -> str:
    if not isinstance(result, dict):
        return str(ErrorClass.unknown)
    err = str(result.get("error") or result.get("message") or "")
    le = err.lower()
    if step_kind.startswith("browser_") or "net::" in le or "timeout" in le or "navigation" in le or "econn" in le:
        if "selector" in le or "strict" in le or "waiting for selector" in le or "element" in le:
            return str(ErrorClass.selector)
        if "net::" in le or "timeout" in le or "navigation" in le or "econn" in le:
            return str(ErrorClass.network)
    if "smtp" in le or "smtplib" in le or "email" in step_kind and ("connection" in le or "refused" in le):
        return str(ErrorClass.network)
    if "status_code" in result or step_kind == "plugin_api" or "http" in le or "httpx" in le:
        sc = int(result.get("status_code") or 0)
        if sc >= 500 or 429 == sc or sc == 408:
            return str(ErrorClass.api)
        if 400 <= sc < 500:
            return str(ErrorClass.validation)
        if "json" in le and "parse" in le:
            return str(ErrorClass.api)
    if "schema" in le or "required" in le or "400" in le or "404" in le and step_kind == "plugin_api":
        return str(ErrorClass.validation)
    if not err:
        return str(ErrorClass.unknown)
    if any(x in le for x in ("connect", "connection", "unreachable", "dns", "getaddrinfo", "name or service")):
        return str(ErrorClass.network)
    return str(ErrorClass.unknown)


def apply_self_heal_strategy(
    step_kind: str,
    payload: dict[str, Any],
    error_class: str,
    attempt_index: int,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """
    Return (new_payload, strategy_id, extra_context).

    ``attempt_index`` is 0-based (first failure before retry=0).
    """
    p = dict(payload)
    extra: dict[str, Any] = {"attempt": attempt_index, "error_class": error_class}

    if step_kind == "browser_click":
        fallbacks = [x for x in (p.get("selector_fallbacks") or []) if str(x).strip()]
        if p.get("selector_alt"):
            fallbacks = [p["selector_alt"]] + fallbacks
        if error_class in (str(ErrorClass.selector), str(ErrorClass.unknown)) and fallbacks and attempt_index < len(fallbacks):
            p["selector"] = fallbacks[attempt_index]
            p["_heal_tried_index"] = attempt_index
            return p, f"selector_fallback_{attempt_index}", {**extra, "selector": p.get("selector")}

    if step_kind == "browser_fill" and error_class in (str(ErrorClass.selector), str(ErrorClass.unknown)):
        alt = p.get("fields_fallback")
        if isinstance(alt, list) and attempt_index < len(alt) and isinstance(alt[attempt_index], dict):
            p["fields"] = alt[attempt_index]
            return p, f"fields_fallback_{attempt_index}", extra

    if step_kind in {"browser_open", "browser_search"} and error_class == str(ErrorClass.network) and attempt_index == 0:
        p["__heal_reload_first"] = True
        return p, "mark_reload", extra

    if step_kind in {"browser_open", "browser_search", "browser_click", "browser_fill"} and error_class == str(ErrorClass.network):
        p["__heal_increase_timeout"] = float(p.get("timeout_ms") or 30000) * 1.5
        return p, "increase_timeout", {**extra, "timeout_ms": p.get("__heal_increase_timeout")}

    if step_kind == "plugin_api" and p.get("alternate_url") and attempt_index == 0 and error_class in (
        str(ErrorClass.network),
        str(ErrorClass.api),
    ):
        p["url"] = str(p.get("alternate_url") or "").strip()
        p["__heal_used_alternate"] = True
        return p, "alternate_url", {**extra, "url": p.get("url")}

    if step_kind == "plugin_api" and error_class == str(ErrorClass.network) and attempt_index > 0:
        p["timeout_seconds"] = min(120.0, float(p.get("timeout_seconds") or 30.0) * 1.5)
        return p, "api_backoff", {**extra}

    if step_kind in {"plugin_email", "email"} and error_class == str(ErrorClass.network) and not p.get("__tried_smtp_again"):
        p["__tried_smtp_again"] = True
        p["__heal_smtp_reconnect"] = True
        return p, "smtp_reconnect", extra

    return p, "no_op", extra
