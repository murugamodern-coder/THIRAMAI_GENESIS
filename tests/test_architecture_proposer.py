"""Tests for :mod:`services.architect.architecture_proposer`.

No database, no Groq calls, no filesystem writes — every external dependency
is mocked via context managers so each test is explicit and self-contained.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.architect.architecture_proposer import (
    _auto_propose_enabled,
    _diff_from_new_file,
    _looks_like_python,
    _max_open_proposals,
    _path_is_safe,
    _proposed_path_for,
    _safe_module_name,
    _split_design_blocks,
    _strip_fences,
    auto_propose_loop,
    detect_capability_gaps,
    get_status,
    propose_module,
)

_NO_DB = "services.architect.architecture_proposer._factory_or_none"


# ---------------------------------------------------------------------------
# _safe_module_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("my_module", "my_module"),
        ("MyModule", "mymodule"),
        ("my-module", "my_module"),
        ("my module", "my_module"),
        ("ab", None),       # too short (< 3 chars final)
        ("a", None),
        ("", None),
        ("123_name", None),  # starts with digit
        ("my_valid_name_42", "my_valid_name_42"),
    ],
)
def test_safe_module_name(raw, expected):
    assert _safe_module_name(raw) == expected


def test_safe_module_name_strips_dots_and_slashes():
    """../../evil → strips to 'evil' which IS valid (3+ chars, starts with 'e')."""
    result = _safe_module_name("../../evil")
    assert result == "evil"  # non-alpha chars stripped, 'evil' is valid


def test_safe_module_name_max_length():
    """Max is 40 extra chars after first → 41 total; 42 would be too long."""
    # 41 'x' → matches {2,40} (40 extra after first 'x') → valid
    assert _safe_module_name("x" * 41) == "x" * 41
    # 42 'x' → 41 extra → exceeds {2,40} → None
    assert _safe_module_name("x" * 42) is None


# ---------------------------------------------------------------------------
# _proposed_path_for
# ---------------------------------------------------------------------------


def test_proposed_path_for_returns_dynamic_prefix():
    path = _proposed_path_for("my_module")
    assert path == "services/dynamic/my_module.py"


# ---------------------------------------------------------------------------
# _path_is_safe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, safe",
    [
        ("services/dynamic/my_module.py", True),
        ("services/dynamic/sub/other.py", True),   # subdirectory IS allowed
        ("services/core/bad.py", False),
        ("../escape.py", False),
        ("alembic/versions/bad.py", False),
        ("core/auth/evil.py", False),
        ("core/security/evil.py", False),
        ("core/db/models.py", False),
        ("core/database.py", False),
        ("core/middleware/bad.py", False),
        ("core/dangerous/bad.py", False),
        ("core/rate_limit/bad.py", False),
        ("settings.py", False),
        ("app.py", False),
        ("services/dynamic/foo.txt", False),  # must end in .py
    ],
)
def test_path_is_safe(path, safe):
    ok, _reason = _path_is_safe(path)
    assert ok == safe, f"Expected safe={safe} for {path!r}"


def test_path_is_safe_returns_reason_on_failure():
    ok, reason = _path_is_safe("app.py")
    assert not ok
    assert isinstance(reason, str) and len(reason) > 0


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_removes_markdown_block():
    raw = "```python\nprint('hello')\n```"
    assert _strip_fences(raw) == "print('hello')"


def test_strip_fences_no_fences_unchanged():
    raw = "print('hello')"
    assert _strip_fences(raw) == "print('hello')"


def test_strip_fences_empty_string():
    assert _strip_fences("") == ""


# ---------------------------------------------------------------------------
# _split_design_blocks
# ---------------------------------------------------------------------------


def test_split_design_blocks_all_three_sections():
    text = (
        "# SUMMARY\nThis is a great module.\n"
        "# CODE\ndef hello(): pass\n"
        "# TESTS\ndef test_hello(): hello()\n"
    )
    blocks = _split_design_blocks(text)
    assert "summary" in blocks and "code" in blocks and "tests" in blocks
    assert "hello" in blocks["code"]
    assert "test_hello" in blocks["tests"]


def test_split_design_blocks_no_sections_treats_as_code():
    raw = "import os\ndef foo(): pass"
    blocks = _split_design_blocks(raw)
    assert "import" in blocks["code"] or "def" in blocks["code"]
    assert blocks["summary"] == ""


def test_split_design_blocks_empty_returns_empty_strings():
    blocks = _split_design_blocks("")
    assert blocks == {"summary": "", "code": "", "tests": ""}


def test_split_design_blocks_case_insensitive_headers():
    text = "# Summary\nSum text\n# Code\ndef x(): pass\n# Tests\ndef t(): pass\n"
    blocks = _split_design_blocks(text)
    assert "def x" in blocks["code"]


# ---------------------------------------------------------------------------
# _looks_like_python
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        ("import os\ndef hello(): pass", True),
        ("class Foo:\n    def bar(self): pass", True),
        ("", False),
        ("x = 1", False),   # no import/def/class
        ("import os\n" + "subprocess.run(['ls'], shell=True)", False),  # shell=True
        ("# tiny", False),  # < 20 chars
    ],
)
def test_looks_like_python(code, expected):
    assert _looks_like_python(code) == expected


def test_looks_like_python_shell_true_rejected():
    code = "import subprocess\ndef run():\n    subprocess.Popen('ls', shell=True)"
    assert _looks_like_python(code) is False


# ---------------------------------------------------------------------------
# _diff_from_new_file
# ---------------------------------------------------------------------------


def test_diff_from_new_file_has_header():
    diff = _diff_from_new_file("services/dynamic/foo.py", "def foo(): pass\n")
    assert "diff --git" in diff
    assert "--- /dev/null" in diff
    assert "+++ b/services/dynamic/foo.py" in diff


def test_diff_from_new_file_has_plus_lines():
    diff = _diff_from_new_file("services/dynamic/foo.py", "def foo(): pass\n")
    plus_lines = [l for l in diff.splitlines() if l.startswith("+")]
    assert any("def foo" in l for l in plus_lines)


def test_diff_from_new_file_line_count_header():
    code = "line one\nline two\nline three"
    diff = _diff_from_new_file("services/dynamic/bar.py", code)
    assert "@@ -0,0 +1,3 @@" in diff


# ---------------------------------------------------------------------------
# _max_open_proposals
# ---------------------------------------------------------------------------


def test_max_open_proposals_default():
    assert _max_open_proposals() == 3


def test_max_open_proposals_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_ARCHITECT_MAX_OPEN_PROPOSALS", "7")
    assert _max_open_proposals() == 7


def test_max_open_proposals_invalid_falls_back(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_ARCHITECT_MAX_OPEN_PROPOSALS", "not_a_number")
    assert _max_open_proposals() == 3


def test_max_open_proposals_minimum_is_one(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_ARCHITECT_MAX_OPEN_PROPOSALS", "-5")
    assert _max_open_proposals() >= 1


# ---------------------------------------------------------------------------
# _auto_propose_enabled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_auto_propose_enabled_truthy_values(value, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_ARCHITECT_AUTO_PROPOSE", value)
    assert _auto_propose_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_auto_propose_disabled_values(value, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_ARCHITECT_AUTO_PROPOSE", value)
    assert _auto_propose_enabled() is False


# ---------------------------------------------------------------------------
# propose_module — validate stages without DB or Groq
# ---------------------------------------------------------------------------


def test_propose_module_invalid_name_rejected():
    result = propose_module(name="ab", need_description="something")
    assert result["ok"] is False
    assert result["stage"] == "validate"
    assert "name" in result["error"]


def test_propose_module_no_groq_key_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = propose_module(name="my_module", need_description="test capability")
    assert result["ok"] is False
    assert result["stage"] == "design"
    assert "GROQ" in result["error"]


def test_propose_module_throttle_when_too_many_open(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake_key")
    with patch(
        "services.architect.architecture_proposer.open_proposals_count",
        return_value=10,
    ):
        result = propose_module(name="my_module", need_description="test")
    assert result["ok"] is False
    assert result["stage"] == "throttle"


# ---------------------------------------------------------------------------
# auto_propose_loop
# ---------------------------------------------------------------------------


def test_auto_propose_loop_disabled_skips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("THIRAMAI_ARCHITECT_AUTO_PROPOSE", raising=False)
    result = auto_propose_loop()
    assert result["ok"] is True
    assert result.get("skipped") is True
    assert "disabled" in result.get("reason", "")


def test_auto_propose_loop_cap_reached_skips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_ARCHITECT_AUTO_PROPOSE", "1")
    with patch(
        "services.architect.architecture_proposer.open_proposals_count",
        return_value=99,
    ):
        result = auto_propose_loop()
    assert result["ok"] is True
    assert result.get("skipped") is True
    assert "cap" in result.get("reason", "")


def test_auto_propose_loop_no_gaps_skips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("THIRAMAI_ARCHITECT_AUTO_PROPOSE", "1")
    with patch(
        "services.architect.architecture_proposer.open_proposals_count",
        return_value=0,
    ), patch(
        "services.architect.architecture_proposer.detect_capability_gaps",
        return_value=[],
    ):
        result = auto_propose_loop()
    assert result["ok"] is True
    assert result.get("skipped") is True
    assert "no_gaps" in result.get("reason", "")


# ---------------------------------------------------------------------------
# detect_capability_gaps — DB-free
# ---------------------------------------------------------------------------


def test_detect_capability_gaps_no_db_returns_empty():
    with patch(_NO_DB, return_value=None):
        result = detect_capability_gaps()
    assert isinstance(result, list)
    assert result == []


# ---------------------------------------------------------------------------
# get_status — DB-free
# ---------------------------------------------------------------------------


def test_get_status_db_free():
    with patch(_NO_DB, return_value=None):
        status = get_status()
    assert "open_proposals" in status
    assert "max_open_proposals" in status
    assert "groq_available" in status
    assert "auto_propose_enabled" in status
    assert isinstance(status["groq_available"], bool)
