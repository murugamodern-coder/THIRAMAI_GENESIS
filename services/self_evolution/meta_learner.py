"""
Meta-learning (MAML-style): learn an initialization that adapts quickly on new tasks.

Uses a small linear head with mean-squared error so inner/outer loops are real
gradients (testable, stable). Optional hooks read :mod:`services.ml.online_learner`
for calibration only — no training side effects.
"""

from __future__ import annotations

import copy
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _as_vec_x(raw: Any, dim: int) -> np.ndarray:
    if isinstance(raw, np.ndarray):
        x = raw.astype(float, copy=False).reshape(-1)
    else:
        x = np.asarray(list(raw), dtype=float).reshape(-1)
    if x.shape[0] != dim:
        raise ValueError(f"feature dim mismatch: expected {dim}, got {x.shape[0]}")
    return x


@dataclass
class Task:
    """A few-shot learning task (support / query split)."""

    task_id: str
    domain: str
    task_type: str  # "classification", "regression", "decision"
    support_set: list[dict[str, Any]]
    query_set: list[dict[str, Any]]
    difficulty: float  # 0–1, estimated difficulty
    created_at: datetime


@dataclass
class MetaLearningResult:
    """Outcome of adapting meta-parameters to one task."""

    initial_params: dict[str, np.ndarray]
    adapted_params: dict[str, np.ndarray]
    pre_adaptation_loss: float
    post_adaptation_loss: float
    improvement: float
    num_gradient_steps: int
    adaptation_time_ms: float
    inner_lr_used: float


class MAML:
    """
    First-order MAML on a linear model: y_hat = W·x + b.

    Inner loop: gradient steps on the support set.
    Meta-update: average query-set gradients evaluated at adapted parameters.
    """

    def __init__(
        self,
        *,
        feature_dim: int = 4,
        inner_lr: float = 0.1,
        outer_lr: float = 0.05,
        num_inner_steps: int = 5,
        task_batch_size: int = 5,
        rng: np.random.Generator | None = None,
    ) -> None:
        self.feature_dim = int(feature_dim)
        self.inner_lr = float(inner_lr)
        self.outer_lr = float(outer_lr)
        self.num_inner_steps = int(num_inner_steps)
        self.task_batch_size = int(max(1, task_batch_size))
        self.rng = rng or np.random.default_rng()
        self.meta_params: dict[str, np.ndarray] | None = None

    def _initialize_params(self) -> dict[str, np.ndarray]:
        d = self.feature_dim
        return {
            "W": self.rng.normal(0, 0.01, size=d).astype(float),
            "b": np.zeros(1, dtype=float),
        }

    def _linear_pred(self, params: dict[str, np.ndarray], x: np.ndarray) -> float:
        return float(np.dot(params["W"], x) + float(params["b"][0]))

    def _compute_loss(self, params: dict[str, np.ndarray], examples: list[dict[str, Any]]) -> float:
        if not examples:
            return 0.0
        se = []
        for ex in examples:
            y = float(ex["y"])
            x = _as_vec_x(ex["x"], self.feature_dim)
            err = self._linear_pred(params, x) - y
            se.append(err * err)
        return float(0.5 * np.mean(se))

    def _grad_batch(
        self, params: dict[str, np.ndarray], examples: list[dict[str, Any]]
    ) -> dict[str, np.ndarray]:
        d = self.feature_dim
        if not examples:
            return {"W": np.zeros(d, dtype=float), "b": np.zeros(1, dtype=float)}
        g_w = np.zeros(d, dtype=float)
        g_b = 0.0
        n = len(examples)
        for ex in examples:
            x = _as_vec_x(ex["x"], self.feature_dim)
            y = float(ex["y"])
            err = self._linear_pred(params, x) - y
            g_w += err * x
            g_b += err
        return {"W": g_w / n, "b": np.array([g_b / n], dtype=float)}

    def _apply_gradients(
        self,
        params: dict[str, np.ndarray],
        gradients: dict[str, np.ndarray],
        lr: float,
    ) -> dict[str, np.ndarray]:
        return {
            "W": params["W"] - lr * gradients["W"],
            "b": params["b"] - lr * gradients["b"],
        }

    def meta_train(self, tasks: list[Task], num_iterations: int = 20) -> dict[str, np.ndarray]:
        if len(tasks) < 1:
            logger.warning("meta_train: no tasks")
            return self.meta_params or self._initialize_params()
        if self.meta_params is None:
            self.meta_params = self._initialize_params()

        for iteration in range(int(num_iterations)):
            k = min(self.task_batch_size, len(tasks))
            idx = self.rng.choice(len(tasks), size=k, replace=False)
            batch = [tasks[int(i)] for i in idx]
            meta_grad_w = np.zeros(self.feature_dim, dtype=float)
            meta_grad_b = np.zeros(1, dtype=float)

            for task in batch:
                inner_lr = self._inner_lr_scaled(task.difficulty)
                theta = copy.deepcopy(self.meta_params)
                for _ in range(self.num_inner_steps):
                    g = self._grad_batch(theta, task.support_set)
                    theta = self._apply_gradients(theta, g, inner_lr)
                g_q = self._grad_batch(theta, task.query_set)
                meta_grad_w += g_q["W"]
                meta_grad_b += g_q["b"]

            n_batch = float(len(batch))
            self.meta_params = self._apply_gradients(
                self.meta_params,
                {"W": meta_grad_w / n_batch, "b": meta_grad_b / n_batch},
                self.outer_lr,
            )

            if iteration % 10 == 0 or iteration == num_iterations - 1:
                avg = self._evaluate_tasks(tasks[: min(5, len(tasks))])
                logger.info("meta-iteration %s: avg_query_loss=%.6f", iteration, avg)

        return self.meta_params

    def _inner_lr_scaled(self, difficulty: float) -> float:
        """Harder tasks use a smaller inner step for stability."""
        d = float(np.clip(difficulty, 0.0, 1.0))
        return float(self.inner_lr * (1.0 - 0.5 * d))

    def _evaluate_tasks(self, tasks: list[Task]) -> float:
        if not tasks or self.meta_params is None:
            return 0.0
        losses = [self._compute_loss(self.meta_params, t.query_set) for t in tasks]
        return float(np.mean(losses))

    def adapt(self, task: Task) -> MetaLearningResult:
        if self.meta_params is None:
            raise ValueError("Must meta-train before adapting")
        t0 = datetime.now(timezone.utc)
        inner_lr = self._inner_lr_scaled(task.difficulty)
        pre = self._compute_loss(self.meta_params, task.query_set)
        adapted = copy.deepcopy(self.meta_params)
        for _ in range(self.num_inner_steps):
            g = self._grad_batch(adapted, task.support_set)
            adapted = self._apply_gradients(adapted, g, inner_lr)
        post = self._compute_loss(adapted, task.query_set)
        elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000.0
        return MetaLearningResult(
            initial_params=copy.deepcopy(self.meta_params),
            adapted_params=adapted,
            pre_adaptation_loss=pre,
            post_adaptation_loss=post,
            improvement=float(pre - post),
            num_gradient_steps=self.num_inner_steps,
            adaptation_time_ms=float(elapsed_ms),
            inner_lr_used=inner_lr,
        )


def online_learner_meta_context() -> dict[str, Any]:
    """Read-only snapshot for meta-learner calibration (no writes)."""
    try:
        from services.ml.online_learner import get_status

        st = get_status()
        return {"integrated": True, **st}
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("online_learner_meta_context failed: %s", exc)
        return {"integrated": False, "error": str(exc)}


class MetaLearner:
    """Orchestrates MAML, task library, similarity, transfer, and optional online-learner calibration."""

    def __init__(
        self,
        *,
        maml: MAML | None = None,
        feature_dim: int = 4,
    ) -> None:
        self.maml = maml or MAML(feature_dim=feature_dim)
        self.tasks: list[Task] = []
        self._base_outer_lr = float(self.maml.outer_lr)
        self._task_adapted_cache: dict[str, dict[str, np.ndarray]] = {}

    def add_task(self, task: Task) -> None:
        self.tasks.append(task)
        logger.info("meta_learner: added task %s (library size=%s)", task.task_id, len(self.tasks))

    def inner_lr_for_task(self, task: Task) -> float:
        """Per-task inner learning rate (difficulty-aware)."""
        return float(self.maml._inner_lr_scaled(task.difficulty))

    def meta_train(self, num_iterations: int = 20) -> dict[str, np.ndarray] | None:
        if len(self.tasks) < 2:
            logger.warning("meta_learner: need at least 2 tasks for meta-training")
            if len(self.tasks) == 1 and self.maml.meta_params is None:
                self.maml.meta_params = self.maml._initialize_params()
            return self.maml.meta_params
        return self.maml.meta_train(self.tasks, num_iterations)

    def adapt_to_new_task(self, task: Task) -> MetaLearningResult:
        result = self.maml.adapt(task)
        self._task_adapted_cache[task.task_id] = copy.deepcopy(result.adapted_params)
        return result

    def adapt_with_transfer(self, task: Task, *, blend: float = 0.35) -> MetaLearningResult:
        """Few-shot adapt starting from meta init blended with the most similar cached task."""
        if self.maml.meta_params is None:
            raise ValueError("Must meta-train before adapting")
        similar = self.find_similar_tasks(task, top_k=1)
        theta0 = copy.deepcopy(self.maml.meta_params)
        if similar and similar[0][1] >= 0.5:
            peer, sim = similar[0]
            cached = self._task_adapted_cache.get(peer.task_id)
            if cached is not None:
                a = float(np.clip(blend * sim, 0.0, 0.99))
                theta0 = {
                    "W": (1 - a) * theta0["W"] + a * cached["W"],
                    "b": (1 - a) * theta0["b"] + a * cached["b"],
                }
        saved = self.maml.meta_params
        try:
            self.maml.meta_params = theta0
            return self.adapt_to_new_task(task)
        finally:
            self.maml.meta_params = saved

    def find_similar_tasks(self, task: Task, top_k: int = 3) -> list[tuple[Task, float]]:
        scored: list[tuple[Task, float]] = []
        for t in self.tasks:
            if t.task_id == task.task_id:
                continue
            scored.append((t, self._compute_task_similarity(task, t)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: max(0, int(top_k))]

    def transfer_gain_vs_baseline(
        self, task: Task, *, blend: float = 0.35
    ) -> tuple[float, float, float]:
        """Return (improvement_plain, improvement_transfer, delta)."""
        base = self.adapt_to_new_task(task)
        imp_plain = base.improvement
        # restore cache entry if adapt_to_new_task overwrote same task
        self._task_adapted_cache.pop(task.task_id, None)
        xfer = self.adapt_with_transfer(task, blend=blend)
        return imp_plain, xfer.improvement, float(xfer.improvement - imp_plain)

    def apply_online_learner_calibration(
        self, *, min_samples: int = 20, max_outer_lr: float = 0.2
    ) -> dict[str, Any]:
        """
        Scale meta outer learning rate using rolling accuracy from the online learner.

        Low accuracy → slightly more aggressive meta steps (capped); high accuracy → dampen.
        """
        ctx = online_learner_meta_context()
        if not ctx.get("integrated"):
            return {"applied": False, "reason": "online_learner_unavailable", "context": ctx}
        samples = int(ctx.get("samples_seen") or 0)
        if samples < min_samples:
            return {"applied": False, "reason": "insufficient_samples", "samples_seen": samples}
        acc = float(np.clip(ctx.get("rolling_accuracy") or 0.0, 0.0, 1.0))
        # worse accuracy -> scale up outer lr modestly
        scale = 0.75 + (1.0 - acc) * 0.5
        new_lr = float(np.clip(self._base_outer_lr * scale, 1e-6, max_outer_lr))
        self.maml.outer_lr = new_lr
        return {
            "applied": True,
            "outer_lr": new_lr,
            "scale": scale,
            "rolling_accuracy": acc,
            "samples_seen": samples,
        }

    @staticmethod
    def _compute_task_similarity(task1: Task, task2: Task) -> float:
        sim = 0.0
        if task1.domain == task2.domain:
            sim += 0.4
        if task1.task_type == task2.task_type:
            sim += 0.3
        diff = abs(float(task1.difficulty) - float(task2.difficulty))
        sim += 0.3 * (1.0 - diff)
        # Optional: align support feature means when shapes match
        try:
            dim = None
            vecs: list[np.ndarray] = []
            for ex in task1.support_set[:8]:
                raw = ex.get("x")
                if raw is None:
                    continue
                v = np.asarray(raw, dtype=float).reshape(-1)
                dim = v.shape[0]
                vecs.append(v)
            v2: list[np.ndarray] = []
            for ex in task2.support_set[:8]:
                raw = ex.get("x")
                if raw is None:
                    continue
                v = np.asarray(raw, dtype=float).reshape(-1)
                if dim is not None and v.shape[0] == dim:
                    v2.append(v)
            if vecs and v2 and dim:
                m1 = np.mean(np.stack(vecs), axis=0)
                m2 = np.mean(np.stack(v2), axis=0)
                denom = float(np.linalg.norm(m1) * np.linalg.norm(m2) + 1e-8)
                cos = float(np.dot(m1, m2) / denom)
                sim += 0.1 * float(np.clip(cos, -1.0, 1.0))
        except Exception:
            pass
        return float(np.clip(sim, 0.0, 1.0))


_meta_learner: MetaLearner | None = None
_meta_lock = threading.Lock()


def get_meta_learner() -> MetaLearner:
    global _meta_learner
    if _meta_learner is None:
        with _meta_lock:
            if _meta_learner is None:
                _meta_learner = MetaLearner()
    return _meta_learner


def reset_meta_learner() -> None:
    global _meta_learner
    with _meta_lock:
        _meta_learner = None


__all__ = [
    "MAML",
    "MetaLearner",
    "MetaLearningResult",
    "Task",
    "get_meta_learner",
    "online_learner_meta_context",
    "reset_meta_learner",
]
