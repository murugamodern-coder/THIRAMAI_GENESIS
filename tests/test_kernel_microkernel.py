"""Micro-kernel: patch validation and hot-reload file helpers (no Docker required)."""

from __future__ import annotations

from pathlib import Path

from core.kernel import hot_reload
from services import self_coder_agent


def test_patch_targets_allowed_core_services_only():
    diff = """diff --git a/core/foo.py b/core/foo.py
--- a/core/foo.py
+++ b/core/foo.py
@@ -1,1 +1,1 @@
-x
+y
"""
    ok, msg = self_coder_agent.patch_targets_allowed(diff)
    assert ok, msg


def test_patch_targets_rejects_traversal():
    diff = """diff --git a/../etc/passwd b/../etc/passwd
--- a/../etc/passwd
+++ b/../etc/passwd
"""
    ok, msg = self_coder_agent.patch_targets_allowed(diff)
    assert not ok


def test_patch_targets_rejects_api_folder():
    diff = """diff --git a/api/routes/x.py b/api/routes/x.py
--- a/api/routes/x.py
+++ b/api/routes/x.py
"""
    ok, msg = self_coder_agent.patch_targets_allowed(diff)
    assert not ok


def test_hot_reload_invokes_ci_cd_when_flag(monkeypatch, tmp_path):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("THIRAMAI_CI_CD_ON_HOT_RELOAD", "1")
    monkeypatch.setattr(hot_reload, "_repo_root", lambda: tmp_path)
    called: list[dict] = []

    def _fake(**kwargs):
        called.append(kwargs)
        return {"ok": True, "channel": "skipped"}

    import services.ci_cd_trigger as _ct

    monkeypatch.setattr(_ct, "trigger_after_sandbox_approval", _fake)
    hot_reload.publish_hot_reload(
        patch_relative_path="var/sandbox_patches/candidate.patch",
        pytest_exit_code=0,
        log_tail="tail",
    )
    assert len(called) == 1
    assert called[0]["source"] == "hot_reload"
    assert called[0]["pytest_exit_code"] == 0


def test_hot_reload_file_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(hot_reload, "_repo_root", lambda: tmp_path)
    hot_reload.publish_hot_reload(
        patch_relative_path="var/sandbox_patches/candidate.patch",
        pytest_exit_code=0,
        log_tail="ok",
    )
    p = hot_reload.peek_pending()
    assert p is not None
    assert p.get("pytest_exit_code") == 0
    assert "candidate.patch" in str(p.get("patch_relative_path", ""))
    hot_reload.clear_pending()
    assert hot_reload.peek_pending() is None


def test_kernel_capabilities_shape():
    from core.kernel.bridge import kernel_capabilities

    c = kernel_capabilities()
    assert c["name"] == "thiramai-genesis-kernel"
    assert "sandbox" in c
