"""
Automatic feature generation and coarse selection for tabular data.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MAX_NUMERIC_FOR_PAIRS = 14


class AutoFeatureEngineer:
    """Interaction + simple transforms; optional correlation-based trimming."""

    def __init__(self, *, max_pairwise_numeric: int = _MAX_NUMERIC_FOR_PAIRS) -> None:
        self.feature_importance: dict[str, float] = {}
        self._max_pairs = int(max_pairwise_numeric)

    def generate_features(
        self,
        data: pd.DataFrame,
        target_col: str | None = None,
        *,
        top_k: int = 50,
    ) -> pd.DataFrame:
        if data.empty:
            return data.copy()

        base = data.drop(columns=[target_col], errors="ignore") if target_col else data
        features = base.copy()
        numeric_cols = list(base.select_dtypes(include=[np.number]).columns)[: self._max_pairs]

        for i, col1 in enumerate(numeric_cols):
            for col2 in numeric_cols[i + 1 :]:
                features[f"{col1}_x_{col2}"] = base[col1] * base[col2]

        for col in numeric_cols:
            features[f"{col}_squared"] = base[col] ** 2

        for col in numeric_cols:
            s = base[col]
            if bool((s > 0).all()):
                features[f"{col}_log"] = np.log(s + 1e-8)

        if "timestamp" in base.columns:
            ts = pd.to_datetime(base["timestamp"], errors="coerce")
            for col in numeric_cols:
                roll = pd.Series(base[col].values, index=ts).sort_index().rolling(5, min_periods=1)
                features[f"{col}_rolling_mean_5"] = roll.mean().values
                features[f"{col}_rolling_std_5"] = roll.std().fillna(0).values
        elif getattr(base.index, "name", None) == "timestamp":
            ts = pd.to_datetime(base.index, errors="coerce")
            for col in numeric_cols:
                roll = pd.Series(base[col].values, index=ts).sort_index().rolling(5, min_periods=1)
                features[f"{col}_rolling_mean_5"] = roll.mean().values
                features[f"{col}_rolling_std_5"] = roll.std().fillna(0).values

        if target_col and target_col in data.columns:
            target = data[target_col]
            features = self._select_features(features, target, target_col, top_k=top_k)
        else:
            logger.info("feature_engineer: produced %d columns (no selection)", len(features.columns))

        return features

    def _select_features(
        self,
        features: pd.DataFrame,
        target: pd.Series,
        target_name: str,
        *,
        top_k: int,
    ) -> pd.DataFrame:
        correlations: dict[str, float] = {}
        for col in features.columns:
            if col == target_name:
                continue
            try:
                s = pd.to_numeric(features[col], errors="coerce")
                y = pd.to_numeric(target, errors="coerce")
                mask = ~(s.isna() | y.isna())
                if int(mask.sum()) < 2:
                    correlations[col] = 0.0
                    continue
                c = np.corrcoef(s[mask].to_numpy(dtype=float), y[mask].to_numpy(dtype=float))[0, 1]
                if np.isnan(c):
                    correlations[col] = 0.0
                else:
                    correlations[col] = abs(float(c))
            except Exception:
                correlations[col] = 0.0

        ordered = sorted(correlations.items(), key=lambda x: x[1], reverse=True)
        top_features = [f[0] for f in ordered[: max(1, top_k)]]
        self.feature_importance = dict(ordered[: max(1, top_k)])
        logger.info("feature_engineer: selected %d / %d features", len(top_features), len(features.columns))
        return features[top_features]

    def get_important_features(self, top_k: int = 10) -> dict[str, float]:
        ordered = sorted(self.feature_importance.items(), key=lambda x: x[1], reverse=True)
        return dict(ordered[:top_k])


_eng_singleton: AutoFeatureEngineer | None = None
_eng_lock = threading.Lock()


def get_feature_engineer() -> AutoFeatureEngineer:
    global _eng_singleton
    if _eng_singleton is None:
        with _eng_lock:
            if _eng_singleton is None:
                _eng_singleton = AutoFeatureEngineer()
    return _eng_singleton


def reset_feature_engineer() -> None:
    global _eng_singleton
    with _eng_lock:
        _eng_singleton = None


__all__ = [
    "AutoFeatureEngineer",
    "get_feature_engineer",
    "reset_feature_engineer",
]
