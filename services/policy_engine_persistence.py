"""
Disk persistence for the :class:`PolicyEngine` LinUCB bandit so contextual
weights survive process restarts.

Notes
-----

* Storage path is ``var/policy_engine/`` by default (the ``var/`` tree is
  already in ``.gitignore``). Override with ``THIRAMAI_POLICY_STATE_PATH``.
* Saves are **atomic**: write to ``<path>.tmp``, ``fsync``, then ``os.replace``
  onto the target.
* Backups: the previous ``bandit_weights.joblib`` is rotated into
  ``backups/bandit_weights_<UTC-timestamp>.joblib`` and only the most recent
  ``THIRAMAI_POLICY_STATE_KEEP`` (default 10) backups are retained.
* Loads validate ``n_features`` and the per-arm matrix shapes; any mismatch is
  rejected and the engine starts from a clean posterior — better than
  resurrecting incompatible weights silently.
* The auto-save hook is **idempotent**: re-applying it to the same engine has
  no effect, so re-running the lifecycle registrar on a hot-reloaded module
  cannot double-wrap ``update_from_outcome``.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np

from services.policy_engine import LinUCBBandit, PolicyEngine, get_policy_engine

logger = logging.getLogger(__name__)


_DEFAULT_STORAGE = Path("var") / "policy_engine"
_WEIGHTS_FILENAME = "bandit_weights.joblib"
_BACKUP_DIRNAME = "backups"
_AUTO_SAVE_FLAG = "_thiramai_persistence_wrapped"


def _resolve_storage_dir() -> Path:
    raw = (os.getenv("THIRAMAI_POLICY_STATE_PATH") or "").strip()
    base = Path(raw).expanduser() if raw else _DEFAULT_STORAGE
    base.mkdir(parents=True, exist_ok=True)
    (base / _BACKUP_DIRNAME).mkdir(parents=True, exist_ok=True)
    return base


def _retain_backups(backup_dir: Path, keep: int) -> None:
    files = sorted(
        backup_dir.glob("bandit_weights_*.joblib"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[max(0, int(keep)):]:
        try:
            stale.unlink()
        except OSError as exc:
            logger.debug("backup retention: could not remove %s: %s", stale, exc)


def _serialize_actions(bandit: LinUCBBandit) -> dict[str, dict[str, Any]]:
    """Snapshot the bandit posteriors under its lock."""

    out: dict[str, dict[str, Any]] = {}
    with bandit._lock:  # noqa: SLF001 — bandit exposes no public snapshot
        for action, rec in bandit.actions.items():
            out[str(action)] = {
                "A": np.asarray(rec["A"], dtype=float).copy(),
                "b": np.asarray(rec["b"], dtype=float).copy(),
                "count": int(rec.get("count", 0)),
            }
    return out


def _restore_actions(
    bandit: LinUCBBandit, saved: dict[str, dict[str, Any]]
) -> int:
    """Replace the bandit posteriors with ``saved``, returning #arms restored."""

    n = bandit.n_features
    restored: dict[str, dict[str, Any]] = {}
    for action, rec in (saved or {}).items():
        try:
            A = np.asarray(rec["A"], dtype=float)
            b = np.asarray(rec["b"], dtype=float)
        except Exception:
            logger.warning("persistence: skip arm %r — malformed payload", action)
            continue
        if A.shape != (n, n) or b.shape != (n,):
            logger.warning(
                "persistence: skip arm %r — shape mismatch A=%s b=%s expected=(%s,%s)/(%s,)",
                action,
                A.shape,
                b.shape,
                n,
                n,
                n,
            )
            continue
        restored[str(action)] = {
            "A": A,
            "b": b,
            "count": int(rec.get("count", 0)),
        }

    with bandit._lock:  # noqa: SLF001
        bandit.actions = restored
    return len(restored)


class PolicyStatePersistence:
    """Save / load helper for :class:`PolicyEngine` bandit state."""

    def __init__(self, *, storage_dir: Path | None = None, keep: int | None = None) -> None:
        self.storage_dir = storage_dir or _resolve_storage_dir()
        self.weights_file = self.storage_dir / _WEIGHTS_FILENAME
        self.backup_dir = self.storage_dir / _BACKUP_DIRNAME
        if keep is None:
            try:
                keep = int(os.getenv("THIRAMAI_POLICY_STATE_KEEP") or "10")
            except ValueError:
                keep = 10
        self.keep = max(0, int(keep))

    # -- IO ---------------------------------------------------------------

    def save_state(self, engine: PolicyEngine) -> bool:
        """Atomically persist ``engine`` state. Returns ``True`` on success."""

        try:
            actions = _serialize_actions(engine.bandit)
            payload = {
                "schema_version": 1,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "n_features": int(engine.bandit.n_features),
                "alpha": float(engine.bandit.alpha),
                "actions": actions,
            }

            self.storage_dir.mkdir(parents=True, exist_ok=True)
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            if self.weights_file.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                backup = self.backup_dir / f"bandit_weights_{stamp}.joblib"
                try:
                    self.weights_file.replace(backup)
                except OSError as exc:
                    logger.warning("persistence: backup rotation failed: %s", exc)
                else:
                    _retain_backups(self.backup_dir, self.keep)

            tmp = self.weights_file.with_suffix(self.weights_file.suffix + ".tmp")
            joblib.dump(payload, tmp)
            try:
                # Best-effort fsync so a crash mid-rename doesn't leave a half file.
                fd = os.open(str(tmp), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                pass
            os.replace(tmp, self.weights_file)

            logger.info(
                "PolicyEngine state saved: %d arms n_features=%d -> %s",
                len(actions),
                engine.bandit.n_features,
                self.weights_file,
            )
            return True
        except Exception as exc:
            logger.error("PolicyEngine state save failed: %s", exc, exc_info=True)
            return False

    def load_state(self, engine: PolicyEngine) -> bool:
        """Load weights into ``engine``. Returns ``True`` if any arms restored."""

        if not self.weights_file.exists():
            logger.info("persistence: no saved state at %s", self.weights_file)
            return False
        try:
            payload = joblib.load(self.weights_file)
        except Exception as exc:
            logger.error("PolicyEngine state load failed: %s", exc, exc_info=True)
            return False

        if not isinstance(payload, dict):
            logger.error("persistence: invalid payload type %r", type(payload).__name__)
            return False

        saved_n = int(payload.get("n_features") or 0)
        if saved_n != int(engine.bandit.n_features):
            logger.warning(
                "persistence: n_features mismatch saved=%d current=%d — refusing load",
                saved_n,
                engine.bandit.n_features,
            )
            return False

        n_arms = _restore_actions(engine.bandit, payload.get("actions") or {})
        saved_at = payload.get("saved_at") or "unknown"
        if n_arms:
            logger.info(
                "PolicyEngine state loaded: %d arms (saved_at=%s)", n_arms, saved_at
            )
        return n_arms > 0

    # -- Auto-save wrapping (idempotent) ---------------------------------

    def auto_save_hook(
        self,
        engine: PolicyEngine,
        *,
        every_n_decisions: int = 100,
    ) -> Callable[..., Any] | None:
        """Wrap ``engine.update_from_outcome`` to checkpoint every ``N`` calls.

        Returns the wrapped callable, or ``None`` if the engine was already
        wrapped (no-op).
        """

        if getattr(engine, _AUTO_SAVE_FLAG, False):
            logger.debug("persistence: engine already auto-save wrapped")
            return None

        original = engine.update_from_outcome
        counter_lock = threading.Lock()
        counter = {"n": int(getattr(engine, "decision_count", 0) or 0)}

        def wrapped_update(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            with counter_lock:
                counter["n"] += 1
                engine.decision_count = counter["n"]
                trip = (counter["n"] % max(1, int(every_n_decisions))) == 0
            if trip:
                self.save_state(engine)
            return result

        engine.update_from_outcome = wrapped_update  # type: ignore[method-assign]
        setattr(engine, _AUTO_SAVE_FLAG, True)
        logger.info(
            "persistence: auto-save hook installed (every %d decisions)",
            every_n_decisions,
        )
        return wrapped_update


# ---------------------------------------------------------------------------
# Singleton + convenience init
# ---------------------------------------------------------------------------


_persistence: PolicyStatePersistence | None = None
_persistence_lock = threading.Lock()


def get_persistence() -> PolicyStatePersistence:
    global _persistence
    if _persistence is None:
        with _persistence_lock:
            if _persistence is None:
                _persistence = PolicyStatePersistence()
    return _persistence


def reset_persistence() -> None:
    """Test-only: drop the singleton so a new storage_dir takes effect."""

    global _persistence
    with _persistence_lock:
        _persistence = None


def init_policy_engine_with_persistence(
    *, every_n_decisions: int = 100
) -> PolicyEngine:
    """Bootstrap the singleton :class:`PolicyEngine` with disk persistence."""

    engine = get_policy_engine()
    persistence = get_persistence()
    persistence.load_state(engine)
    persistence.auto_save_hook(engine, every_n_decisions=every_n_decisions)
    return engine


__all__ = [
    "PolicyStatePersistence",
    "get_persistence",
    "init_policy_engine_with_persistence",
    "reset_persistence",
]
