"""
Self-Evolution Phase 3: Reinforcement-learning trading agent (PPO).

Implements a single-asset trading agent on top of a custom Gymnasium
environment. The agent is **always gated**: even when a trained policy is
loaded, ``run_live`` requires:

    THIRAMAI_RL_LIVE_ENABLED=1
    THIRAMAI_RL_MAX_CAPITAL_INR <= 10000   (default cap, hard ceiling)

Anything above the cap is silently clamped. This module is built so that the
rest of the system never breaks when ``stable-baselines3`` / ``gymnasium`` /
``yfinance`` are missing — every public function returns a documented
"unavailable" payload instead of raising.

Public API
----------
- :class:`TradingEnv`              — Gymnasium env with [price, volume, RSI,
  MACD, position, PnL] observation and 3 discrete actions
- :func:`train_ppo`                — fit a PPO agent on historical data
- :func:`backtest`                 — replay a model on a frozen DataFrame
- :func:`run_shadow`               — predict-and-log for N days without
  hitting any broker
- :func:`run_live`                 — production-gated execution (paper-mode
  here; broker integration is a future plug-in)
- :func:`get_status`               — JSON-safe capability snapshot
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.ml.model_registry import (
    ModelRegistry,
    model_artifact_path,
    next_version,
)


def _get_active_or_latest(name: str) -> Any | None:
    """Return the active or latest model record, or ``None`` on any DB failure.

    The model registry raises when the underlying ``ml_models`` migration has
    not been applied yet (e.g. fresh installs or test SQLite). Trading
    helpers should never bubble that up.
    """
    for accessor in (ModelRegistry.get_active, ModelRegistry.get_latest):
        try:
            rec = accessor(name)
        except Exception:
            continue
        if rec is not None:
            return rec
    return None

_LOG = logging.getLogger(__name__)

MODEL_NAME = "rl_trading_ppo"

ACTION_HOLD = 0
ACTION_BUY = 1
ACTION_SELL = 2
ACTION_NAMES = {ACTION_HOLD: "HOLD", ACTION_BUY: "BUY", ACTION_SELL: "SELL"}

# Production safety
HARD_CAP_INR = 10_000
DEFAULT_TRANSACTION_COST_BPS = 5  # 0.05% per side (round-trip ~0.10%)
DEFAULT_DAILY_LOSS_CAP_PCT = 3.0
DEFAULT_RSI_PERIOD = 14

# JSONL trade log path (shadow + live)
_LOG_DIR = Path(os.getenv("THIRAMAI_RL_LOG_DIR") or "var/rl_trades")


# ---------------------------------------------------------------------------
# Optional dependencies (graceful)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - depends on optional deps
    import numpy as np  # type: ignore[import-not-found]

    _NUMPY_AVAILABLE = True
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]
    _NUMPY_AVAILABLE = False

try:  # pragma: no cover
    import gymnasium as gym  # type: ignore[import-not-found]
    from gymnasium import spaces  # type: ignore[import-not-found]

    _GYM_AVAILABLE = True
except Exception:  # pragma: no cover
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    _GYM_AVAILABLE = False

try:  # pragma: no cover
    from stable_baselines3 import PPO  # type: ignore[import-not-found]
    from stable_baselines3.common.vec_env import DummyVecEnv  # type: ignore[import-not-found]

    _SB3_AVAILABLE = True
except Exception as _exc:  # pragma: no cover
    PPO = None  # type: ignore[assignment]
    DummyVecEnv = None  # type: ignore[assignment]
    _SB3_AVAILABLE = False
    _LOG.info("stable-baselines3 unavailable; rl_trading_agent in capability-only mode (%s)", _exc)


def rl_available() -> bool:
    """Return True only when *all* deps (numpy + gym + sb3) are installed."""
    return bool(_NUMPY_AVAILABLE and _GYM_AVAILABLE and _SB3_AVAILABLE)


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------


def load_history(
    symbol: str,
    *,
    period: str = "1y",
    interval: str = "5m",
    exchange_suffix: str = "NS",
) -> list[dict[str, float]]:
    """
    Return a list of OHLCV bars for ``symbol`` (NSE by default).

    Falls back to ``[]`` when ``yfinance`` is missing or the request fails.
    The default of 1 year of 5-minute bars is intentionally aggressive — for
    quick experiments use ``period="3mo"`` or ``interval="1d"``.
    """
    if not _NUMPY_AVAILABLE:
        return []
    try:
        import yfinance as yf  # type: ignore[import-not-found]
    except Exception as exc:
        _LOG.warning("yfinance missing for RL data load: %s", exc)
        return []
    sym = symbol.strip().upper()
    if exchange_suffix and "." not in sym:
        sym = f"{sym}.{exchange_suffix.strip().upper().lstrip('.')}"
    try:
        df = yf.download(sym, period=period, interval=interval, progress=False, threads=False)
    except Exception as exc:
        _LOG.warning("yfinance download failed for %s: %s", sym, exc)
        return []
    if df is None or df.empty:
        return []
    try:
        import pandas as pd  # type: ignore[import-not-found]

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    except Exception:
        pass
    rows: list[dict[str, float]] = []
    for ts, r in df.iterrows():
        try:
            rows.append(
                {
                    "time": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "open": float(r.get("Open") or 0.0),
                    "high": float(r.get("High") or 0.0),
                    "low": float(r.get("Low") or 0.0),
                    "close": float(r.get("Close") or 0.0),
                    "volume": float(r.get("Volume") or 0.0),
                }
            )
        except Exception:
            continue
    return [b for b in rows if b["close"] > 0]


# ---------------------------------------------------------------------------
# Indicator helpers (numpy implementations; mirror stock_indicator_service)
# ---------------------------------------------------------------------------


def _rsi_at(closes: Any, period: int = DEFAULT_RSI_PERIOD) -> float:
    if not _NUMPY_AVAILABLE or closes is None or len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period + 1):].astype(float))
    gains = np.clip(deltas, 0, None).mean()
    losses = np.clip(-deltas, 0, None).mean()
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return float(100.0 - (100.0 / (1.0 + rs)))


def _macd_at(closes: Any) -> float:
    if not _NUMPY_AVAILABLE or closes is None or len(closes) < 35:
        return 0.0
    x = closes.astype(float)
    a12, a26 = 2.0 / 13.0, 2.0 / 27.0
    e12 = e26 = float(x[0])
    macd_line: list[float] = []
    for px in x:
        e12 = a12 * float(px) + (1 - a12) * e12
        e26 = a26 * float(px) + (1 - a26) * e26
        macd_line.append(e12 - e26)
    return float(macd_line[-1])


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _make_env_class():
    """Return TradingEnv subclassing gym.Env when gymnasium is available."""
    if not _GYM_AVAILABLE:  # pragma: no cover
        class _Stub:
            available = False

            def __init__(self, *_a: Any, **_kw: Any) -> None:
                raise RuntimeError("gymnasium unavailable; install gymnasium + stable-baselines3")

        return _Stub

    class _TradingEnv(gym.Env):  # type: ignore[misc, valid-type]
        """Single-asset discrete-action env.

        Observation: ``[price_norm, volume_norm, rsi_norm, macd_norm, position,
        pnl_norm]`` (6-dim float32 in roughly ``[-3, +3]``).
        Action space: ``Discrete(3)`` → ``{HOLD, BUY, SELL}``.
        Reward: per-step PnL minus transaction costs in *currency* normalised
        by the starting capital.
        Episode ends when daily loss cap fires or the data ends.
        """

        metadata = {"render_modes": ["human"]}

        def __init__(
            self,
            bars: list[dict[str, float]],
            *,
            starting_capital_inr: float = 100_000.0,
            max_position_inr: float | None = None,
            transaction_cost_bps: float = DEFAULT_TRANSACTION_COST_BPS,
            daily_loss_cap_pct: float = DEFAULT_DAILY_LOSS_CAP_PCT,
            warmup_bars: int = 35,
        ) -> None:
            super().__init__()
            self._bars = list(bars or [])
            if len(self._bars) < warmup_bars + 5:
                raise ValueError("not enough bars for env (need warmup_bars + 5)")
            self._warmup = int(warmup_bars)
            self._t = self._warmup
            self.starting_capital = float(starting_capital_inr)
            self.max_position = float(max_position_inr or starting_capital_inr)
            self.transaction_cost_bps = float(transaction_cost_bps)
            self.daily_loss_cap_pct = float(daily_loss_cap_pct)
            self.position_qty = 0.0
            self.position_avg = 0.0
            self.cash = float(starting_capital_inr)
            self.realized_pnl = 0.0
            self.peak_equity = float(starting_capital_inr)
            self.trades: list[dict[str, Any]] = []

            self.action_space = spaces.Discrete(3)  # type: ignore[union-attr]
            self.observation_space = spaces.Box(  # type: ignore[union-attr]
                low=-3.0, high=3.0, shape=(6,), dtype=np.float32  # type: ignore[arg-type]
            )

        # -- core gym API ------------------------------------------------

        def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):  # type: ignore[override]
            super().reset(seed=seed)
            self._t = self._warmup
            self.position_qty = 0.0
            self.position_avg = 0.0
            self.cash = float(self.starting_capital)
            self.realized_pnl = 0.0
            self.peak_equity = float(self.starting_capital)
            self.trades = []
            return self._obs(), {"t": self._t}

        def step(self, action: int):  # type: ignore[override]
            action = int(action)
            bar = self._bars[self._t]
            price = float(bar["close"])
            prev_equity = self._equity(price)

            tx_cost = 0.0
            if action == ACTION_BUY and self.cash > 0:
                qty_cap = self.max_position / max(price, 1e-6)
                qty_buy = min(qty_cap, self.cash / max(price, 1e-6))
                if qty_buy > 0:
                    cost = qty_buy * price
                    fee = cost * (self.transaction_cost_bps / 1e4)
                    self.cash -= cost + fee
                    new_qty = self.position_qty + qty_buy
                    if new_qty > 0:
                        self.position_avg = (
                            self.position_avg * self.position_qty + price * qty_buy
                        ) / new_qty
                    self.position_qty = new_qty
                    tx_cost += fee
                    self.trades.append(
                        {
                            "t": self._t,
                            "action": "BUY",
                            "price": price,
                            "qty": qty_buy,
                            "fee": fee,
                        }
                    )
            elif action == ACTION_SELL and self.position_qty > 0:
                qty_sell = self.position_qty
                proceeds = qty_sell * price
                fee = proceeds * (self.transaction_cost_bps / 1e4)
                pnl = (price - self.position_avg) * qty_sell - fee
                self.cash += proceeds - fee
                self.realized_pnl += pnl
                self.position_qty = 0.0
                self.position_avg = 0.0
                tx_cost += fee
                self.trades.append(
                    {
                        "t": self._t,
                        "action": "SELL",
                        "price": price,
                        "qty": qty_sell,
                        "pnl": pnl,
                        "fee": fee,
                    }
                )

            # Advance time
            self._t += 1
            terminated = False
            truncated = self._t >= len(self._bars) - 1

            new_price = float(self._bars[min(self._t, len(self._bars) - 1)]["close"])
            equity = self._equity(new_price)
            self.peak_equity = max(self.peak_equity, equity)
            drawdown_pct = 100.0 * (self.peak_equity - equity) / max(self.peak_equity, 1.0)
            if drawdown_pct >= self.daily_loss_cap_pct:
                terminated = True

            reward_currency = (equity - prev_equity) - tx_cost
            reward = reward_currency / max(self.starting_capital, 1.0)

            return self._obs(), float(reward), bool(terminated), bool(truncated), {
                "equity": equity,
                "cash": self.cash,
                "position_qty": self.position_qty,
                "drawdown_pct": drawdown_pct,
                "realized_pnl": self.realized_pnl,
            }

        # -- helpers -----------------------------------------------------

        def _equity(self, price: float) -> float:
            return float(self.cash + self.position_qty * float(price))

        def _obs(self):
            i = min(max(self._t, 0), len(self._bars) - 1)
            window = self._bars[max(0, i - 50):i + 1]
            closes = np.asarray([b["close"] for b in window], dtype=float)
            volumes = np.asarray([b.get("volume", 0.0) for b in window], dtype=float)
            price = float(closes[-1])
            mean_close = float(np.mean(closes)) if len(closes) > 0 else price
            std_close = float(np.std(closes)) if len(closes) > 1 else 1.0
            price_norm = (price - mean_close) / max(std_close, 1e-6)
            vol_now = float(volumes[-1])
            vol_mean = float(np.mean(volumes)) if len(volumes) > 0 else 0.0
            vol_norm = (vol_now - vol_mean) / max(float(np.std(volumes) or 1.0), 1e-6)
            rsi = _rsi_at(closes)
            rsi_norm = (rsi - 50.0) / 50.0
            macd = _macd_at(closes)
            macd_norm = max(-3.0, min(3.0, macd / max(abs(price), 1.0)))
            position_signed = 1.0 if self.position_qty > 0 else 0.0
            equity = self._equity(price)
            pnl_norm = (equity - self.starting_capital) / max(self.starting_capital, 1.0)
            obs = np.asarray(
                [
                    price_norm,
                    vol_norm,
                    rsi_norm,
                    macd_norm,
                    position_signed,
                    pnl_norm,
                ],
                dtype=np.float32,
            )
            return np.clip(obs, -3.0, 3.0)

    return _TradingEnv


TradingEnv = _make_env_class()


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------


def train_ppo(
    *,
    symbol: str = "^NSEI",
    period: str = "1y",
    interval: str = "5m",
    exchange_suffix: str = "NS",
    total_timesteps: int = 50_000,
    starting_capital_inr: float = 100_000.0,
    activate: bool = True,
) -> dict[str, Any]:
    """Fit a PPO agent on historical bars and register the artifact.

    Returns a JSON-safe dict; ``ok=False`` when deps or data are missing.
    """
    if not rl_available():
        return {
            "ok": False,
            "error": "rl_dependencies_missing",
            "available": rl_available(),
        }

    bars = load_history(
        symbol, period=period, interval=interval, exchange_suffix=exchange_suffix
    )
    if len(bars) < 250:
        return {
            "ok": False,
            "error": f"insufficient_bars ({len(bars)} < 250)",
            "bars": len(bars),
        }

    try:
        env = TradingEnv(bars, starting_capital_inr=starting_capital_inr)
        vec = DummyVecEnv([lambda: TradingEnv(bars, starting_capital_inr=starting_capital_inr)])  # type: ignore[misc]
        model = PPO(
            "MlpPolicy",
            vec,
            verbose=0,
            learning_rate=3e-4,
            gamma=0.99,
            n_steps=2048,
            batch_size=64,
            seed=42,
        )
        model.learn(total_timesteps=int(total_timesteps))
    except Exception as exc:
        _LOG.exception("rl_trading_agent.train_failed")
        return {"ok": False, "error": f"train_failed: {exc!s}"[:200]}

    bt = backtest_in_env(model, env)
    metrics = {
        "accuracy": float(bt.get("win_rate") or 0.0),
        "total_return_pct": bt.get("total_return_pct"),
        "sharpe": bt.get("sharpe"),
        "max_drawdown_pct": bt.get("max_drawdown_pct"),
        "trades": bt.get("trades"),
        "symbol": symbol,
        "period": period,
        "interval": interval,
    }

    version = next_version(MODEL_NAME)
    artifact = model_artifact_path(MODEL_NAME, version)
    try:
        model.save(str(artifact))
    except Exception as exc:
        return {"ok": False, "error": f"persist_failed: {exc!s}"[:200], "metrics": metrics}

    try:
        rec = ModelRegistry.register(
            name=MODEL_NAME,
            version=version,
            metrics=metrics,
            path=str(artifact),
            training_samples=int(total_timesteps),
            notes=f"symbol={symbol} period={period} interval={interval}",
            activate=activate,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"register_failed: {exc!s}"[:200],
            "metrics": metrics,
            "model_path": str(artifact),
        }
    return {
        "ok": True,
        "version": version,
        "metrics": metrics,
        "model_path": str(artifact),
        "registered": rec.to_dict() if rec else None,
        "active": bool(activate),
    }


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def backtest_in_env(model: Any, env: Any) -> dict[str, Any]:
    """Replay ``model`` on ``env`` and produce summary statistics."""
    if not rl_available():
        return {"ok": False, "error": "rl_dependencies_missing"}
    obs, _info = env.reset()
    rewards: list[float] = []
    equities: list[float] = []
    trades = 0
    while True:
        try:
            action, _ = model.predict(obs, deterministic=True)
        except Exception:
            break
        obs, reward, terminated, truncated, info = env.step(int(action))
        rewards.append(float(reward))
        equities.append(float(info.get("equity") or 0.0))
        if action != ACTION_HOLD:
            trades += 1
        if terminated or truncated:
            break

    final_equity = equities[-1] if equities else env.starting_capital
    total_return_pct = 100.0 * (final_equity / env.starting_capital - 1.0)
    if len(rewards) >= 2 and np is not None:
        arr = np.asarray(rewards, dtype=float)
        sigma = float(np.std(arr))
        mean = float(np.mean(arr))
        sharpe = float((mean / sigma) * math.sqrt(252)) if sigma > 1e-9 else 0.0
    else:
        sharpe = 0.0
    if equities:
        peak = equities[0]
        max_dd = 0.0
        for e in equities:
            peak = max(peak, e)
            dd = 100.0 * (peak - e) / max(peak, 1.0)
            max_dd = max(max_dd, dd)
    else:
        max_dd = 0.0
    sells = [t for t in env.trades if t.get("action") == "SELL"]
    wins = sum(1 for t in sells if (t.get("pnl") or 0.0) > 0)
    win_rate = (wins / len(sells)) if sells else 0.0
    return {
        "ok": True,
        "trades": int(len(env.trades)),
        "round_trips": len(sells),
        "win_rate": round(win_rate, 4),
        "total_return_pct": round(total_return_pct, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd, 4),
        "final_equity_inr": round(float(final_equity), 2),
        "starting_capital_inr": round(float(env.starting_capital), 2),
    }


def backtest(
    *,
    symbol: str = "^NSEI",
    period: str = "1y",
    interval: str = "5m",
    exchange_suffix: str = "NS",
    starting_capital_inr: float = 100_000.0,
) -> dict[str, Any]:
    """Run the active PPO model against fresh historical data and report stats."""
    if not rl_available():
        return {"ok": False, "error": "rl_dependencies_missing"}
    rec = _get_active_or_latest(MODEL_NAME)
    if rec is None or not rec.model_path:
        return {"ok": False, "error": "no_active_model"}
    bars = load_history(
        symbol, period=period, interval=interval, exchange_suffix=exchange_suffix
    )
    if len(bars) < 250:
        return {"ok": False, "error": f"insufficient_bars ({len(bars)} < 250)"}
    try:
        model = PPO.load(rec.model_path)  # type: ignore[union-attr]
    except Exception as exc:
        return {"ok": False, "error": f"model_load_failed: {exc!s}"[:200]}
    env = TradingEnv(bars, starting_capital_inr=starting_capital_inr)
    return backtest_in_env(model, env)


# ---------------------------------------------------------------------------
# Shadow + Live (gated)
# ---------------------------------------------------------------------------


def _append_log(payload: dict[str, Any]) -> None:
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = _LOG_DIR / f"trades_{datetime.now(timezone.utc).date().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except Exception as exc:
        _LOG.debug("rl trade log append failed: %s", exc)


def run_shadow(
    *,
    symbol: str = "^NSEI",
    interval: str = "5m",
    exchange_suffix: str = "NS",
    bars_to_replay: int = 78,
    starting_capital_inr: float = 100_000.0,
) -> dict[str, Any]:
    """
    Run the active model in *shadow mode*: predicts and **logs** intended
    trades to ``var/rl_trades/trades_<DATE>.jsonl`` but never sends an order.

    ``bars_to_replay`` defaults to 78 ≈ one trading day of 5-minute bars.
    """
    if not rl_available():
        return {"ok": False, "error": "rl_dependencies_missing"}
    rec = _get_active_or_latest(MODEL_NAME)
    if rec is None or not rec.model_path:
        return {"ok": False, "error": "no_active_model"}
    bars = load_history(
        symbol, period="5d", interval=interval, exchange_suffix=exchange_suffix
    )[-int(bars_to_replay) - 50:]
    if len(bars) < 50:
        return {"ok": False, "error": "insufficient_bars"}
    try:
        model = PPO.load(rec.model_path)  # type: ignore[union-attr]
    except Exception as exc:
        return {"ok": False, "error": f"model_load_failed: {exc!s}"[:200]}
    env = TradingEnv(bars, starting_capital_inr=starting_capital_inr)
    obs, _info = env.reset()
    actions_taken: list[str] = []
    while True:
        try:
            action, _ = model.predict(obs, deterministic=True)
        except Exception:
            break
        obs, _reward, terminated, truncated, info = env.step(int(action))
        actions_taken.append(ACTION_NAMES.get(int(action), "?"))
        _append_log(
            {
                "mode": "shadow",
                "symbol": symbol,
                "version": rec.version,
                "action": ACTION_NAMES.get(int(action), "?"),
                "equity": info.get("equity"),
                "drawdown_pct": info.get("drawdown_pct"),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        if terminated or truncated:
            break
    bt = backtest_in_env(model, env)
    return {
        "ok": True,
        "mode": "shadow",
        "model_version": rec.version,
        "actions": actions_taken,
        "summary": bt,
    }


def _live_capital_capped(requested_inr: float) -> float:
    cap_env = os.getenv("THIRAMAI_RL_MAX_CAPITAL_INR")
    try:
        cap = float(cap_env) if cap_env else float(HARD_CAP_INR)
    except ValueError:
        cap = float(HARD_CAP_INR)
    return max(0.0, min(float(requested_inr or 0.0), cap, float(HARD_CAP_INR)))


def run_live(
    *,
    symbol: str = "^NSEI",
    interval: str = "5m",
    exchange_suffix: str = "NS",
    requested_capital_inr: float = float(HARD_CAP_INR),
    broker_executor: Any | None = None,
) -> dict[str, Any]:
    """
    Live-fire the model. Requires ``THIRAMAI_RL_LIVE_ENABLED=1`` and capital
    is hard-capped to ``HARD_CAP_INR`` (₹10,000 by default). When
    ``broker_executor`` is ``None`` this function performs paper execution
    only; integrate with your broker by passing ``broker_executor(action,
    qty, price) -> dict``.
    """
    if not rl_available():
        return {"ok": False, "error": "rl_dependencies_missing"}
    if (os.getenv("THIRAMAI_RL_LIVE_ENABLED") or "").strip() not in ("1", "true", "yes", "on"):
        return {"ok": False, "error": "live_disabled (set THIRAMAI_RL_LIVE_ENABLED=1)"}

    capital = _live_capital_capped(requested_capital_inr)
    if capital <= 0:
        return {"ok": False, "error": "capital_zero_after_cap"}

    rec = _get_active_or_latest(MODEL_NAME)
    if rec is None or not rec.model_path:
        return {"ok": False, "error": "no_active_model"}
    bars = load_history(
        symbol, period="1d", interval=interval, exchange_suffix=exchange_suffix
    )
    if len(bars) < 50:
        return {"ok": False, "error": "insufficient_bars"}

    try:
        model = PPO.load(rec.model_path)  # type: ignore[union-attr]
    except Exception as exc:
        return {"ok": False, "error": f"model_load_failed: {exc!s}"[:200]}
    env = TradingEnv(bars, starting_capital_inr=capital, max_position_inr=capital)
    obs, _info = env.reset()
    try:
        action, _ = model.predict(obs, deterministic=True)
    except Exception as exc:
        return {"ok": False, "error": f"predict_failed: {exc!s}"[:200]}
    action_name = ACTION_NAMES.get(int(action), "?")

    broker_result: dict[str, Any] = {"executed": False, "reason": "no_broker_executor"}
    if broker_executor is not None and action != ACTION_HOLD:
        try:
            price = float(bars[-1]["close"])
            qty = capital / max(price, 1e-6)
            broker_result = dict(broker_executor(action_name, qty, price) or {})
            broker_result.setdefault("executed", True)
        except Exception as exc:
            broker_result = {"executed": False, "error": f"broker_failed: {exc!s}"[:200]}

    _append_log(
        {
            "mode": "live",
            "symbol": symbol,
            "version": rec.version,
            "capital_inr": capital,
            "action": action_name,
            "broker_result": broker_result,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {
        "ok": True,
        "mode": "live",
        "symbol": symbol,
        "model_version": rec.version,
        "capital_inr": capital,
        "action": action_name,
        "broker_result": broker_result,
    }


# ---------------------------------------------------------------------------
# Status probe
# ---------------------------------------------------------------------------


def get_status() -> dict[str, Any]:
    """Capability snapshot for ``/personal/os/brain-health`` and ops dashboards."""
    rec = _get_active_or_latest(MODEL_NAME)
    return {
        "rl_available": rl_available(),
        "stable_baselines3": _SB3_AVAILABLE,
        "gymnasium": _GYM_AVAILABLE,
        "active_model": rec.to_dict() if rec else None,
        "hard_cap_inr": HARD_CAP_INR,
        "live_enabled": (os.getenv("THIRAMAI_RL_LIVE_ENABLED") or "0") in ("1", "true", "yes", "on"),
    }


__all__ = [
    "ACTION_BUY",
    "ACTION_HOLD",
    "ACTION_NAMES",
    "ACTION_SELL",
    "DEFAULT_DAILY_LOSS_CAP_PCT",
    "DEFAULT_TRANSACTION_COST_BPS",
    "HARD_CAP_INR",
    "MODEL_NAME",
    "TradingEnv",
    "backtest",
    "backtest_in_env",
    "get_status",
    "load_history",
    "rl_available",
    "run_live",
    "run_shadow",
    "train_ppo",
]
