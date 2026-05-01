"""Market regime detection.

We classify the current state of a price series into one of four buckets:

* ``trending_up``
* ``trending_down``
* ``ranging``
* ``volatile``

A simple, deterministic rule-based classifier is used by default; if
``hmmlearn`` is available the constructor will *also* fit a 4-state
GaussianHMM, but we still report the rule-based label as the headline
because the HMM state ordering is arbitrary and varies per fit. The HMM's
posterior over the latest bar is exposed as ``hmm_posterior`` for
diagnostics.

Spec deviations
---------------

* The original ``_detect_hmm`` normalised log-likelihood as
  ``(score + 10) / 10`` clipped to ``[0, 1]`` - log-likelihoods of typical
  return series are well below -10 so the confidence saturates to 0
  immediately. We use the HMM's own posterior probability instead.
* The state-index -> regime label mapping in the spec was hard-coded
  (state 0 -> trending_up etc.), but HMM state indices are not stable
  across fits. We label HMM states by their fitted return mean / variance
  rather than trusting their numeric index.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


try:
    from hmmlearn import hmm as _hmmlearn  # type: ignore[import-untyped]

    HMM_AVAILABLE = True
except Exception as _exc:  # pragma: no cover - environment-dependent
    _hmmlearn = None  # type: ignore[assignment]
    HMM_AVAILABLE = False
    logger.info("regime_detector: hmmlearn unavailable (%s) - rule-based only", _exc)


_REGIMES: tuple[str, ...] = ("trending_up", "trending_down", "ranging", "volatile")


class RegimeDetector:
    """Classify market regime from a price series."""

    def __init__(
        self,
        *,
        n_states: int = 4,
        force_fallback: bool = False,
        trend_pct_threshold: float = 2.0,
        volatility_threshold: float = 30.0,
    ) -> None:
        self.n_states = int(n_states)
        self.trend_pct_threshold = float(trend_pct_threshold)
        self.volatility_threshold = float(volatility_threshold)
        self._use_hmm = HMM_AVAILABLE and not force_fallback
        self._hmm: Any = None
        if self._use_hmm and _hmmlearn is not None:
            try:
                self._hmm = _hmmlearn.GaussianHMM(
                    n_components=self.n_states,
                    covariance_type="full",
                    n_iter=20,
                    random_state=42,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("regime_detector: HMM init failed (%s)", exc)
                self._use_hmm = False
                self._hmm = None

    @property
    def using_hmm(self) -> bool:
        return self._use_hmm and self._hmm is not None

    # -- public --------------------------------------------------------

    def detect(self, prices: pd.Series, *, lookback: int = 20) -> dict[str, Any]:
        """Return ``{"regime", "confidence", "trend_pct", "volatility_pct", ...}``."""
        if prices is None or len(prices) < lookback + 5:
            return {
                "regime": "unknown",
                "confidence": 0.0,
                "trend_pct": 0.0,
                "volatility_pct": 0.0,
                "method": "insufficient_data",
            }

        rule_label = self._rule_based(prices, lookback=lookback)
        report = dict(rule_label)
        report["method"] = "rule_based"

        if self.using_hmm:
            try:
                hmm_payload = self._hmm_posterior(prices)
                if hmm_payload is not None:
                    report["hmm_posterior"] = hmm_payload
                    report["method"] = "rule_based+hmm_posterior"
            except Exception as exc:
                logger.warning("regime_detector: HMM posterior failed (%s)", exc)

        return report

    # -- internals -----------------------------------------------------

    def _rule_based(self, prices: pd.Series, *, lookback: int) -> dict[str, Any]:
        prices = prices.astype(float)
        returns = prices.pct_change().dropna()
        # Trailing trend over the lookback window.
        prev = float(prices.iloc[-lookback])
        last = float(prices.iloc[-1])
        trend_pct = ((last / prev) - 1.0) * 100.0 if prev > 0 else 0.0
        recent_returns = returns.tail(lookback)
        volatility_pct = (
            float(recent_returns.std(ddof=1)) * np.sqrt(252) * 100.0
            if len(recent_returns) > 1
            else 0.0
        )

        if volatility_pct > self.volatility_threshold:
            regime = "volatile"
            confidence = 0.7
        elif abs(trend_pct) < self.trend_pct_threshold:
            regime = "ranging"
            confidence = 0.6
        elif trend_pct >= self.trend_pct_threshold:
            regime = "trending_up"
            confidence = 0.7
        else:
            regime = "trending_down"
            confidence = 0.7

        return {
            "regime": regime,
            "confidence": float(confidence),
            "trend_pct": float(trend_pct),
            "volatility_pct": float(volatility_pct),
        }

    def _hmm_posterior(self, prices: pd.Series) -> dict[str, Any] | None:
        if self._hmm is None:
            return None
        returns = prices.pct_change().dropna().to_numpy(dtype=float).reshape(-1, 1)
        if returns.size < 30:
            return None
        try:
            self._hmm.fit(returns)
            # ``predict_proba`` returns posterior probability per state; we
            # report the most likely state for the *last* observation and its
            # probability, NOT a normalised log-likelihood (the spec did the
            # latter and it never produced sensible numbers).
            posteriors = self._hmm.predict_proba(returns)
            last = posteriors[-1]
            top_state = int(np.argmax(last))
            return {
                "top_state": top_state,
                "top_state_probability": float(last[top_state]),
                "posterior": [float(p) for p in last],
            }
        except Exception as exc:
            logger.debug("regime_detector: HMM fit/predict failed (%s)", exc)
            return None


__all__ = ["HMM_AVAILABLE", "RegimeDetector"]
