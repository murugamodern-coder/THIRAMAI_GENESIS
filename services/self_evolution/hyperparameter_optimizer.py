"""
Bayesian hyperparameter optimization (GP surrogate + Expected Improvement).

Falls back to local exploration around the incumbent when the GP is ill-conditioned.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from scipy.stats import norm  # type: ignore[import-untyped]

    _SCIPY_NORM = norm
except Exception:  # pragma: no cover
    _SCIPY_NORM = None

try:
    from sklearn.gaussian_process import GaussianProcessRegressor  # type: ignore[import-untyped]
    from sklearn.gaussian_process.kernels import Matern, WhiteKernel  # type: ignore[import-untyped]
    from sklearn.gaussian_process.kernels import ConstantKernel as C  # type: ignore[import-untyped]

    _SKLEARN_GPR = True
except Exception:  # pragma: no cover
    GaussianProcessRegressor = None  # type: ignore[misc, assignment]
    _SKLEARN_GPR = False


@dataclass
class HyperparameterSpace:
    """Single tunable dimension."""

    param_name: str
    param_type: str  # "float", "int", "categorical"
    bounds: tuple[float, float]
    choices: list[Any] | None = None


@dataclass
class TrialResult:
    """One evaluated hyperparameter vector."""

    trial_id: int
    params: dict[str, Any]
    score: float
    duration_ms: float
    timestamp: datetime


def _expected_improvement(
    mu: np.ndarray, sigma: np.ndarray, y_best: float, *, xi: float = 0.01
) -> np.ndarray:
    """EI for maximization (analytic)."""
    mu = np.asarray(mu, dtype=float).reshape(-1)
    sigma = np.asarray(sigma, dtype=float).reshape(-1)
    if _SCIPY_NORM is None:
        return np.maximum(mu - y_best, 0.0)
    sigma = np.maximum(sigma, 1e-9)
    imp = mu - y_best - xi
    z = imp / sigma
    normal = _SCIPY_NORM
    ei = imp * normal.cdf(z) + sigma * normal.pdf(z)
    return np.maximum(ei, 0.0)


class BayesianOptimizer:
    """Vectorized search space with GP-EI after ``n_initial_random`` Sobol-like uniform draws."""

    def __init__(
        self,
        param_space: list[HyperparameterSpace],
        *,
        n_initial_random: int = 5,
        n_candidates: int = 512,
        rng: np.random.Generator | None = None,
    ) -> None:
        self.param_space = list(param_space)
        self.n_initial_random = int(n_initial_random)
        self.n_candidates = int(max(32, n_candidates))
        self.rng = rng or np.random.default_rng()
        self.trials: list[TrialResult] = []

    def suggest_next_params(self) -> dict[str, Any]:
        if len(self.trials) < self.n_initial_random:
            return self._random_sample()
        if not _SKLEARN_GPR or GaussianProcessRegressor is None:
            return self._fallback_around_best()
        gp_sample = self._gp_ei_sample()
        if gp_sample is not None:
            return gp_sample
        return self._fallback_around_best()

    def record_trial(self, params: dict[str, Any], score: float, duration_ms: float) -> TrialResult:
        trial = TrialResult(
            trial_id=len(self.trials),
            params=dict(params),
            score=float(score),
            duration_ms=float(duration_ms),
            timestamp=datetime.now(timezone.utc),
        )
        self.trials.append(trial)
        logger.info("bayes_opt: trial %s score=%.5f params=%s", trial.trial_id, trial.score, trial.params)
        return trial

    def get_best_params(self) -> tuple[dict[str, Any], float]:
        if not self.trials:
            return {}, float("-inf")
        best = max(self.trials, key=lambda t: t.score)
        return dict(best.params), float(best.score)

    # --- encoding (all dimensions → [0,1] box) ---

    def _encode(self, params: dict[str, Any]) -> np.ndarray:
        vec: list[float] = []
        for sp in self.param_space:
            v = params[sp.param_name]
            if sp.param_type == "float":
                lo, hi = sp.bounds
                span = max(hi - lo, 1e-12)
                vec.append((float(v) - lo) / span)
            elif sp.param_type == "int":
                lo, hi = sp.bounds
                span = max(float(hi) - float(lo), 1.0)
                vec.append((float(int(v)) - float(lo)) / span)
            elif sp.param_type == "categorical":
                choices = sp.choices or []
                if not choices:
                    vec.append(0.0)
                else:
                    try:
                        idx = choices.index(v)
                    except ValueError:
                        idx = self.rng.integers(0, len(choices))
                    denom = max(len(choices) - 1, 1)
                    vec.append(float(idx) / float(denom))
            else:
                vec.append(0.0)
        return np.clip(np.asarray(vec, dtype=float), 0.0, 1.0)

    def _decode(self, u: np.ndarray) -> dict[str, Any]:
        u = np.asarray(u, dtype=float).reshape(-1)
        out: dict[str, Any] = {}
        for i, sp in enumerate(self.param_space):
            t = float(np.clip(u[i] if i < len(u) else 0.5, 0.0, 1.0))
            if sp.param_type == "float":
                lo, hi = sp.bounds
                out[sp.param_name] = float(lo + t * (hi - lo))
            elif sp.param_type == "int":
                lo, hi = int(sp.bounds[0]), int(sp.bounds[1])
                val = int(round(lo + t * (hi - lo)))
                out[sp.param_name] = int(np.clip(val, lo, hi))
            elif sp.param_type == "categorical":
                choices = list(sp.choices or [])
                if not choices:
                    out[sp.param_name] = None
                else:
                    idx = int(round(t * (len(choices) - 1)))
                    idx = int(np.clip(idx, 0, len(choices) - 1))
                    out[sp.param_name] = choices[idx]
            else:
                out[sp.param_name] = None
        return out

    def _random_sample(self) -> dict[str, Any]:
        u = self.rng.uniform(0.0, 1.0, size=len(self.param_space))
        return self._decode(u)

    def _fallback_around_best(self) -> dict[str, Any]:
        best_params, _ = self.get_best_params()
        if not best_params:
            return self._random_sample()
        u0 = self._encode(best_params)
        noise = self.rng.normal(0, 0.12, size=u0.shape)
        u = np.clip(u0 + noise, 0.0, 1.0)
        return self._decode(u)

    def _fit_gp(self) -> GaussianProcessRegressor | None:  # type: ignore[valid-type]
        if len(self.trials) < 2 or GaussianProcessRegressor is None:
            return None
        X = np.stack([self._encode(t.params) for t in self.trials], axis=0)
        y = np.asarray([t.score for t in self.trials], dtype=float)
        if np.allclose(y, y[0]):
            return None
        kernel = C(1.0, (1e-2, 1e2)) * Matern(nu=2.5, length_scale_bounds=(1e-2, 1e2)) + WhiteKernel(1e-4)
        gpr = GaussianProcessRegressor(
            kernel=kernel,
            alpha=1e-6,
            normalize_y=True,
            random_state=int(self.rng.integers(0, 2**31 - 1)),
        )
        try:
            gpr.fit(X, y)
            return gpr
        except Exception as exc:
            logger.debug("bayes_opt: GPR fit failed: %s", exc)
            return None

    def _gp_ei_sample(self) -> dict[str, Any] | None:
        gpr = self._fit_gp()
        if gpr is None:
            return None
        _, y_best = self.get_best_params()
        dims = len(self.param_space)
        candidates = self.rng.uniform(0.0, 1.0, size=(self.n_candidates, dims))
        try:
            mu, sigma = gpr.predict(candidates, return_std=True)
        except Exception:
            return None
        ei = _expected_improvement(mu, sigma, y_best)
        idx = int(np.argmax(ei))
        if ei[idx] <= 1e-12:
            return None
        return self._decode(candidates[idx])


class HyperparameterTuner:
    """Namespaced optimizers for several components (or NAS-style categorical spaces)."""

    def __init__(self, rng: np.random.Generator | None = None) -> None:
        self.rng = rng or np.random.default_rng()
        self.optimizers: dict[str, BayesianOptimizer] = {}

    def tune_component(
        self,
        component_name: str,
        param_space: list[HyperparameterSpace],
        objective_function: Callable[[dict[str, Any]], float],
        *,
        n_trials: int = 20,
        n_initial_random: int = 5,
    ) -> dict[str, Any]:
        optimizer = BayesianOptimizer(param_space, n_initial_random=n_initial_random, rng=self.rng)
        self.optimizers[component_name] = optimizer
        for _ in range(int(n_trials)):
            params = optimizer.suggest_next_params()
            t0 = datetime.now(timezone.utc)
            try:
                score = float(objective_function(params))
            except Exception as exc:
                logger.warning("tuner: objective error for %s: %s", component_name, exc)
                score = float("-inf")
            dt_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000.0
            optimizer.record_trial(params, score, dt_ms)
        best_params, best_score = optimizer.get_best_params()
        logger.info("tuner: %s best_score=%.5f params=%s", component_name, best_score, best_params)
        return dict(best_params)

    def get_tuned_params(self, component_name: str) -> dict[str, Any] | None:
        opt = self.optimizers.get(component_name)
        if opt is None:
            return None
        params, _ = opt.get_best_params()
        return dict(params) if params else None


@dataclass
class LightweightNASResult:
    """Best discrete architecture found via the same BO loop (categorical dims)."""

    component_name: str
    best_config: dict[str, Any]
    best_score: float
    trial_count: int


class LightweightNAS:
    """
    Small architecture search: expose depth / width / activation as categorical or int dims
    and reuse :class:`BayesianOptimizer`.
    """

    def __init__(self, rng: np.random.Generator | None = None) -> None:
        self.rng = rng or np.random.default_rng()

    def run(
        self,
        *,
        name: str,
        objective: Callable[[dict[str, Any]], float],
        spaces: list[HyperparameterSpace],
        n_trials: int = 16,
    ) -> LightweightNASResult:
        tuner = HyperparameterTuner(rng=self.rng)
        best = tuner.tune_component(name, spaces, objective, n_trials=n_trials, n_initial_random=min(4, n_trials))
        opt = tuner.optimizers[name]
        _, score = opt.get_best_params()
        return LightweightNASResult(
            component_name=name,
            best_config=dict(best),
            best_score=float(score),
            trial_count=len(opt.trials),
        )


_tuner_singleton: HyperparameterTuner | None = None
_tuner_lock = threading.Lock()


def get_hyperparameter_tuner() -> HyperparameterTuner:
    global _tuner_singleton
    if _tuner_singleton is None:
        with _tuner_lock:
            if _tuner_singleton is None:
                _tuner_singleton = HyperparameterTuner()
    return _tuner_singleton


def reset_hyperparameter_tuner() -> None:
    global _tuner_singleton
    with _tuner_lock:
        _tuner_singleton = None


__all__ = [
    "BayesianOptimizer",
    "HyperparameterSpace",
    "HyperparameterTuner",
    "LightweightNAS",
    "LightweightNASResult",
    "TrialResult",
    "get_hyperparameter_tuner",
    "reset_hyperparameter_tuner",
]
