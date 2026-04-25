"""
Self-Evolution Phase 1: ML model registry.

DB-backed registry of ML model versions. Tracks accuracy, training samples, and
which version is active for each model name. The artifact path is recorded but
the artifact itself lives on disk (default ``/app/models`` or ``./var/models``
when running outside Docker).

Public API
----------
- ``register(name, version, metrics, path, *, training_samples, notes)``
- ``activate(name, version)``                — atomically set this version active
- ``get_latest(name)``                       — most recently trained row
- ``get_active(name)``                       — currently active row (may be None)
- ``compare_versions(name, top_n=5)``        — ordered comparison of recent versions
- ``retire(name, version)``                  — mark a version inactive
- ``models_dir()`` / ``model_artifact_path(name, version)`` — disk helpers

Versioning convention: semver strings like ``"1.0.3"``. ``next_version(name)``
returns the next patch bump; callers may pass any string they want.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from core.database import get_session_factory
from core.db.models import MLModel

_LOG = logging.getLogger(__name__)

_DEFAULT_MODELS_DIR_DOCKER = "/app/models"
_DEFAULT_MODELS_DIR_LOCAL = "var/models"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass
class ModelRecord:
    """Plain snapshot of an ``ml_models`` row (decoupled from session lifecycle)."""

    id: int
    name: str
    version: str
    accuracy: float
    metrics: dict[str, Any]
    training_samples: int
    trained_at: datetime
    is_active: bool
    model_path: str
    notes: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "accuracy": round(float(self.accuracy or 0.0), 4),
            "metrics": dict(self.metrics or {}),
            "training_samples": int(self.training_samples or 0),
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "is_active": bool(self.is_active),
            "model_path": str(self.model_path or ""),
            "notes": self.notes,
        }


def _row_to_record(row: MLModel) -> ModelRecord:
    return ModelRecord(
        id=int(row.id),
        name=str(row.name),
        version=str(row.version),
        accuracy=float(row.accuracy or 0.0),
        metrics=dict(row.metrics or {}),
        training_samples=int(row.training_samples or 0),
        trained_at=row.trained_at,
        is_active=bool(row.is_active),
        model_path=str(row.model_path or ""),
        notes=row.notes,
    )


def models_dir() -> Path:
    """Return the directory used to persist serialized model artifacts."""
    override = (os.getenv("THIRAMAI_MODELS_DIR") or "").strip()
    if override:
        path = Path(override)
    elif Path(_DEFAULT_MODELS_DIR_DOCKER).parent.exists() and os.access(
        Path(_DEFAULT_MODELS_DIR_DOCKER).parent, os.W_OK
    ):
        path = Path(_DEFAULT_MODELS_DIR_DOCKER)
    else:
        path = Path.cwd() / _DEFAULT_MODELS_DIR_LOCAL
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_artifact_path(name: str, version: str) -> Path:
    """Convention for the on-disk artifact path of a model version."""
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]+", "_", str(name).strip()) or "model"
    safe_ver = re.sub(r"[^a-zA-Z0-9_\.\-]+", "_", str(version).strip()) or "0.0.1"
    return models_dir() / f"{safe_name}__v{safe_ver}.pkl"


def next_version(name: str) -> str:
    """Return the next semver patch bump for ``name`` (``0.0.1`` if first).

    Falls back to a timestamp-based version if the latest version is not semver.
    """
    latest = get_latest(name)
    if latest is None:
        return "0.0.1"
    m = _VERSION_RE.match(str(latest.version or ""))
    if not m:
        return f"0.0.{int(datetime.now(timezone.utc).timestamp())}"
    major, minor, patch = (int(x) for x in m.groups())
    return f"{major}.{minor}.{patch + 1}"


class ModelRegistry:
    """Thin DB-backed registry; methods are class-level for easy import."""

    @staticmethod
    def register(
        name: str,
        version: str,
        metrics: dict[str, Any],
        path: str | Path,
        *,
        training_samples: int = 0,
        notes: str | None = None,
        activate: bool = False,
    ) -> ModelRecord | None:
        """Insert a new ``(name, version)`` row. Returns ``None`` if duplicate."""
        factory = _factory_or_none()
        if factory is None:
            return None
        accuracy = float(((metrics or {}).get("accuracy") or 0.0))
        with factory() as session:
            existing = (
                session.execute(
                    select(MLModel).where(
                        MLModel.name == str(name), MLModel.version == str(version)
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                return _row_to_record(existing)
            row = MLModel(
                name=str(name),
                version=str(version),
                accuracy=accuracy,
                metrics=dict(metrics or {}),
                training_samples=int(training_samples or 0),
                is_active=False,
                model_path=str(path),
                notes=notes,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            rec = _row_to_record(row)
        if activate:
            ModelRegistry.activate(name, version)
            rec.is_active = True
        return rec

    @staticmethod
    def activate(name: str, version: str) -> bool:
        """Atomically mark a single version as active for this model name."""
        factory = _factory_or_none()
        if factory is None:
            return False
        with factory() as session:
            session.execute(
                update(MLModel)
                .where(MLModel.name == str(name), MLModel.is_active.is_(True))
                .values(is_active=False)
            )
            res = session.execute(
                update(MLModel)
                .where(MLModel.name == str(name), MLModel.version == str(version))
                .values(is_active=True)
            )
            session.commit()
            return int(res.rowcount or 0) > 0

    @staticmethod
    def retire(name: str, version: str) -> bool:
        """Mark a version inactive without deleting the row."""
        factory = _factory_or_none()
        if factory is None:
            return False
        with factory() as session:
            res = session.execute(
                update(MLModel)
                .where(MLModel.name == str(name), MLModel.version == str(version))
                .values(is_active=False)
            )
            session.commit()
            return int(res.rowcount or 0) > 0

    @staticmethod
    def get_latest(name: str) -> ModelRecord | None:
        factory = _factory_or_none()
        if factory is None:
            return None
        with factory() as session:
            row = (
                session.execute(
                    select(MLModel)
                    .where(MLModel.name == str(name))
                    .order_by(MLModel.trained_at.desc(), MLModel.id.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
        return _row_to_record(row) if row is not None else None

    @staticmethod
    def get_active(name: str) -> ModelRecord | None:
        factory = _factory_or_none()
        if factory is None:
            return None
        with factory() as session:
            row = (
                session.execute(
                    select(MLModel)
                    .where(MLModel.name == str(name), MLModel.is_active.is_(True))
                    .order_by(MLModel.trained_at.desc(), MLModel.id.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
        return _row_to_record(row) if row is not None else None

    @staticmethod
    def compare_versions(name: str, top_n: int = 5) -> dict[str, Any]:
        """Return a small report comparing the most recent ``top_n`` versions."""
        factory = _factory_or_none()
        if factory is None:
            return {"name": name, "versions": [], "best": None, "active": None}
        n = max(1, min(int(top_n or 5), 20))
        with factory() as session:
            rows = (
                session.execute(
                    select(MLModel)
                    .where(MLModel.name == str(name))
                    .order_by(MLModel.trained_at.desc(), MLModel.id.desc())
                    .limit(n)
                )
                .scalars()
                .all()
            )
        records = [_row_to_record(r) for r in rows]
        best = max(records, key=lambda r: r.accuracy) if records else None
        active = next((r for r in records if r.is_active), None)
        return {
            "name": str(name),
            "versions": [r.to_dict() for r in records],
            "best": best.to_dict() if best else None,
            "active": active.to_dict() if active else None,
        }


def _factory_or_none():
    try:
        return get_session_factory()
    except Exception as exc:
        _LOG.debug("model_registry session factory unavailable: %s", exc)
        return None
