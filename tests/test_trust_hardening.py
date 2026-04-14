"""Trust / safety helpers: tenant guard, uploads, cache, AI envelope."""

from unittest.mock import MagicMock, patch

from api.dependencies import validate_user_access
from core.ai_input_sanitize import sanitize_user_text
from core.ai_output_contract import apply_ai_safety_envelope, estimate_confidence
from core.ai_tool_arg_policy import sanitize_tool_arguments
from core.security.upload_validation import validate_upload_bytes


def test_validate_user_access_no_db():
    with patch("api.dependencies.get_session_factory", return_value=None):
        assert validate_user_access(1, 1) is False


def test_validate_user_access_denied():
    sess = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = sess
    cm.__exit__.return_value = None
    with patch("api.dependencies.get_session_factory", return_value=MagicMock(return_value=cm)), patch(
        "core.security.org_access.validate_user_access", return_value=False
    ):
        assert validate_user_access(5, 9) is False


def test_validate_user_access_ok():
    sess = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = sess
    cm.__exit__.return_value = None
    with patch("api.dependencies.get_session_factory", return_value=MagicMock(return_value=cm)), patch(
        "core.security.org_access.validate_user_access", return_value=True
    ):
        assert validate_user_access(5, 9) is True


def test_upload_rejects_oversize():
    big = b"x" * 200
    with patch("core.security.upload_validation.max_upload_bytes", return_value=100):
        out = validate_upload_bytes(big, filename="a.pdf", content_type="application/pdf", allowed_ext=("pdf",))
    assert out["ok"] is False


def test_upload_accepts_minimal_pdf():
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    out = validate_upload_bytes(pdf, filename="t.pdf", content_type="application/pdf", allowed_ext=("pdf",))
    assert out["ok"] is True


def test_sanitize_user_text_strips_controls():
    s = sanitize_user_text("hello\x00world", max_len=100)
    assert "\x00" not in s


def test_sanitize_tool_arguments_removes_dunder():
    args = sanitize_tool_arguments("x", {"__proto__": 1, "amount": "50"})
    assert "__proto__" not in args
    assert args.get("amount") == "50"


def test_ai_safety_envelope_default_threshold_off():
    d = {"ok": True, "narrative": "unknown market", "response": "unknown market"}
    out = apply_ai_safety_envelope(dict(d), narrative="unknown market", sources=[])
    assert "confidence_score" in out
    assert out["narrative"] == "unknown market"


def test_estimate_confidence_sources_boost():
    c0 = estimate_confidence(narrative="clear answer", sources=[])
    c1 = estimate_confidence(narrative="clear answer", sources=["http://a", "http://b"])
    assert c1 >= c0


def test_cache_layer_memory_fallback():
    from services.cache_layer import get_or_set_cache

    n = {"count": 0}

    def inc():
        n["count"] += 1
        return {"v": n["count"]}

    with patch("services.worker_heartbeat.redis_client", return_value=None):
        a = get_or_set_cache("thiramai:appcache:test_key_x", 60, inc)
        b = get_or_set_cache("thiramai:appcache:test_key_x", 60, inc)
    assert a == b == {"v": 1}


def test_consume_llm_units_no_redis():
    from core.ai_usage_limits import consume_llm_units

    with patch("services.worker_heartbeat.redis_client", return_value=None):
        ok, msg = consume_llm_units(1)
    assert ok is True
