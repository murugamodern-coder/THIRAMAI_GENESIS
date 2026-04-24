"""Post-dispatch verification per step type (email, file, browser, API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _schema_check(obj: Any, schema: dict[str, Any] | None) -> tuple[bool, str]:
    if not schema:
        return True, ""
    if not isinstance(obj, dict):
        return False, "response is not a JSON object"
    required = schema.get("required_keys")
    if isinstance(required, list):
        for k in required:
            if k not in obj:
                return False, f"missing key: {k}"
    types = schema.get("key_types")
    if isinstance(types, dict):
        for k, tname in types.items():
            if k not in obj:
                continue
            v = obj[k]
            if tname == "string" and not isinstance(v, str):
                return False, f"{k} must be string"
            if tname == "number" and not isinstance(v, (int, float)) and not isinstance(v, bool):
                return False, f"{k} must be number"
    return True, ""


def verify_step_outcome(
    step_kind: str,
    result: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """
    Return (verified, detail_dict).

    ``result`` is the raw dispatch result; verification may require payload expectations.
    """
    if not isinstance(result, dict):
        return False, {"reason": "invalid_result", "verify": "type"}

    sk = str(step_kind or "")

    if sk == "plugin_email" or sk == "email":
        if result.get("ok") is True:
            return True, {"verify": "smtp_sent", "to": result.get("to")}
        if result.get("fallback_notification_ok"):
            return True, {"verify": "email_fallback_notify", "notification_id": result.get("notification_id")}
        if result.get("simulated") and payload.get("allow_verify_simulated"):
            return True, {"verify": "simulated_accepted"}
        if result.get("simulated"):
            return False, {"verify": "simulated_not_sent", "error": result.get("error")}
        return False, {"verify": "send_failed", "error": result.get("error")}

    if sk == "plugin_file" or sk == "file":
        if not result.get("ok"):
            return False, {"verify": "no_ok", "error": result.get("error")}
        p = result.get("path")
        if not p:
            return False, {"verify": "no_path"}
        path = Path(str(p))
        if not path.is_file():
            return False, {"verify": "missing_file", "path": str(path)}
        raw = path.read_text(encoding="utf-8", errors="replace")
        if payload.get("expect_content_substring"):
            if str(payload["expect_content_substring"]) not in raw:
                return False, {"verify": "content_mismatch", "hint": "expect_content_substring"}
        if payload.get("min_bytes") and len(raw.encode("utf-8")) < int(payload["min_bytes"]):
            return False, {"verify": "too_small"}
        return True, {"verify": "file_ok", "bytes": result.get("bytes")}

    if sk.startswith("browser_"):
        if not result.get("ok"):
            return False, {"verify": "browser_action_failed", "error": result.get("error")}
        if sk == "browser_open":
            title = str(result.get("title") or "")
            if payload.get("expect_title_substring") and str(payload.get("expect_title_substring") or "") not in title:
                return False, {"verify": "title_mismatch", "title": title[:200]}
            return True, {"verify": "load_ok", "title": title[:200]}
        if sk == "browser_search":
            snip = str(result.get("snippet_preview") or "")
            if len(snip) < 4 and not payload.get("lenient_search_verify"):
                return False, {"verify": "empty_snippet"}
            return True, {"verify": "search_ok", "len": len(snip)}
        if sk == "browser_click":
            if result.get("ok") is not True:
                return False, {"verify": "click_not_ok"}
            return True, {"verify": "click_ok"}
        if sk == "browser_fill":
            if result.get("ok") is not True:
                return False, {"verify": "fill_not_ok"}
            if not (result.get("filled_selectors") or []):
                return False, {"verify": "nothing_filled"}
            return True, {"verify": "fill_ok"}

    if sk == "plugin_api" or sk == "api":
        sc = int(result.get("status_code") or 0)
        if not (200 <= sc < 400) and not result.get("ok"):
            return False, {"verify": "http_status", "status_code": sc}
        if result.get("ok") is not True and sc and not (200 <= sc < 400):
            return False, {"verify": "not_2xx", "status_code": sc}
        schema = payload.get("response_schema")
        if isinstance(payload.get("response_schema"), str):
            try:
                schema = json.loads(str(payload.get("response_schema") or "{}"))
            except Exception:
                schema = None
        body = result.get("json")
        if schema and body is not None:
            ok_s, err_s = _schema_check(body, schema if isinstance(schema, dict) else None)
            if not ok_s:
                return False, {"verify": "schema", "detail": err_s}
        return True, {"verify": "api_ok", "status_code": sc or result.get("status_code")}

    if sk.startswith("internal_") or sk == "plugin_notify":
        if result.get("ok") is True or result.get("simulated"):
            return True, {"verify": "soft_ok" if result.get("simulated") else "ok"}
        return False, {"verify": "internal_fail", "error": result.get("error")}

    if result.get("ok") is True:
        return True, {"verify": "generic_ok"}
    return False, {"verify": "generic_fail"}


