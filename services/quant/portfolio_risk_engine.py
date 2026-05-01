"""Portfolio-level risk engine.

Pre-trade and live monitoring of portfolio risk: position-size limits,
sector caps, beta-weighted market exposure, parametric VaR, peak-to-trough
drawdown, and top-5 concentration.

Key design decisions
--------------------

* **Raw SQL, not ORM.** ``paper_trades`` does not have a SQLAlchemy model in
  this codebase - it's an Alembic-created table queried via raw SQL
  everywhere else (``services.quant.paper_trader``). The original spec
  imported a non-existent ``core.db.models.PaperTrade`` which would crash
  at import time; we mirror the existing raw-SQL pattern.
* **Injectable price provider.** ``paper_trades`` does not store
  ``current_price`` (the column doesn't exist - it is computed at read
  time). The spec read ``pos.current_price`` which would always be
  ``None``. We accept a ``price_provider: Callable[[str], float]`` so
  tests can fake live prices and production can plug in
  ``PaperTrader.get_live_price``.
* **Absolute values for limit checks.** Short positions have negative
  signed market value; netting them against longs in a sector / position
  / concentration check would silently allow over-exposure. All limit
  checks use absolute magnitudes.
* **Org-id aware.** ``paper_trades`` is multi-tenant; the spec read
  every row globally. We filter by ``org_id`` to match
  ``services.quant.paper_trader``.
* **Singleton is thread-safe** with a lock (the spec used a bare module
  global which could double-construct under concurrent first-use).
* **VaR is a parametric variance-sum approximation.** The spec assumed
  positions were uncorrelated; we expose a ``correlation`` parameter so
  callers can dial that assumption (default 0.3 - moderate correlation
  typical of single-country single-asset-class equity portfolios).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy import text

from core.database import get_engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RiskLimits:
    """Hard limits enforced per pre-trade check."""

    max_position_pct: float = 0.20          # 20% of portfolio per symbol
    max_sector_pct: float = 0.40            # 40% per sector
    max_beta_weighted: float = 1.5          # 1.5x market beta exposure
    max_var_95_pct: float = 0.05            # 5% daily 95% VaR
    max_drawdown_pct: float = 0.10          # 10% peak-to-trough
    max_gross_leverage: float = 2.0         # gross / equity
    max_net_exposure_pct: float = 1.0       # |long - short| / equity
    max_concentration_top5: float = 0.60    # top-5 / equity


@dataclass
class PositionRisk:
    """Risk view of a single open position. ``quantity`` is signed (long >0, short <0)."""

    symbol: str
    quantity: int
    entry_price: float
    current_price: float
    market_value: float           # signed: quantity * current_price
    pnl: float
    pnl_pct: float
    beta: float
    sector: str
    position_pct: float           # absolute |market_value| / total_value
    contribution_to_var: float = 0.0


@dataclass
class PortfolioRisk:
    """Aggregate portfolio risk snapshot."""

    total_value: float
    positions: list[PositionRisk] = field(default_factory=list)
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    long_exposure: float = 0.0
    short_exposure: float = 0.0
    sector_exposure: dict[str, float] = field(default_factory=dict)
    portfolio_beta: float = 0.0
    var_95: float = 0.0
    current_drawdown: float = 0.0
    top5_concentration: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl_today: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


# Reasonable defaults for symbol-level metadata. Production deployments
# should override via constructor params or load from a real reference store.
_DEFAULT_SECTOR_MAP: dict[str, str] = {
    "RELIANCE": "Energy",
    "TCS": "IT",
    "INFY": "IT",
    "HDFCBANK": "Finance",
    "ICICIBANK": "Finance",
    "SBIN": "Finance",
    "BHARTIARTL": "Telecom",
    "WIPRO": "IT",
    "ITC": "FMCG",
    "LT": "Infrastructure",
}

_DEFAULT_BETA_MAP: dict[str, float] = {
    "RELIANCE": 1.20,
    "TCS": 0.90,
    "INFY": 0.95,
    "HDFCBANK": 1.10,
    "ICICIBANK": 1.15,
    "SBIN": 1.30,
    "BHARTIARTL": 0.85,
    "WIPRO": 0.90,
    "ITC": 0.70,
    "LT": 1.25,
}


# Sentinel so callers can explicitly say ``engine=None`` to mean "no DB at
# all" (used by tests). Omitting the parameter falls back to ``get_engine()``.
_USE_DEFAULT_ENGINE: Any = object()


class PortfolioRiskEngine:
    """Pre-trade risk gate + post-trade portfolio monitoring."""

    def __init__(
        self,
        limits: RiskLimits | None = None,
        *,
        org_id: int = 1,
        base_capital: float = 100_000.0,
        price_provider: Callable[[str], float] | None = None,
        sector_map: dict[str, str] | None = None,
        beta_map: dict[str, float] | None = None,
        engine: Any = _USE_DEFAULT_ENGINE,
        position_volatility: float = 0.02,
        position_correlation: float = 0.3,
        z_score_95: float = 1.645,
        z_score_99: float = 2.326,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.org_id = int(org_id)
        self.base_capital = float(base_capital)
        # Caller-supplied price source. None disables live MTM (all positions
        # are marked at entry price), which is the safe default.
        self._price_provider = price_provider
        self.sector_map = dict(sector_map) if sector_map is not None else dict(_DEFAULT_SECTOR_MAP)
        self.beta_map = dict(beta_map) if beta_map is not None else dict(_DEFAULT_BETA_MAP)
        # ``engine=None`` is explicit "no DB"; omitting falls back to
        # ``get_engine()`` (default production wiring).
        self._engine = get_engine() if engine is _USE_DEFAULT_ENGINE else engine
        self.position_volatility = float(position_volatility)
        self.position_correlation = max(0.0, min(1.0, float(position_correlation)))
        self.z_score_95 = float(z_score_95)
        self.z_score_99 = float(z_score_99)

    # -- public API ----------------------------------------------------

    def check_trade_allowed(
        self,
        symbol: str,
        quantity: int,
        price: float,
        side: str = "buy",
    ) -> dict[str, Any]:
        """Pre-trade gate. Returns ``{"allowed": bool, "reason": str, ...}``."""
        symbol = (symbol or "").strip().upper()
        side_norm = (side or "").strip().lower()
        if side_norm not in ("buy", "sell"):
            return {
                "allowed": False,
                "reason": f"invalid side {side!r}",
                "risk_metrics": {},
            }
        if quantity <= 0:
            return {"allowed": False, "reason": "quantity must be positive", "risk_metrics": {}}
        if price <= 0:
            return {"allowed": False, "reason": "price must be positive", "risk_metrics": {}}

        portfolio = self._get_portfolio_snapshot()
        if portfolio.total_value <= 0:
            return {
                "allowed": False,
                "reason": "no capital available",
                "risk_metrics": {"total_value": portfolio.total_value},
            }

        signed_qty = quantity if side_norm == "buy" else -quantity
        new_portfolio = self._simulate_trade(portfolio, symbol, signed_qty, price)

        violations: list[str] = []
        position_pct = self._symbol_exposure_pct(new_portfolio, symbol)
        sector = self._get_sector(symbol)
        sector_pct = abs(new_portfolio.sector_exposure.get(sector, 0.0))
        beta_exposure = self._calculate_beta_weighted_exposure(new_portfolio)
        var = self._calculate_var(new_portfolio)
        var_pct = var / new_portfolio.total_value if new_portfolio.total_value > 0 else 0.0
        gross_leverage = (
            new_portfolio.gross_exposure / new_portfolio.total_value
            if new_portfolio.total_value > 0
            else 0.0
        )
        net_exposure_pct = (
            abs(new_portfolio.net_exposure) / new_portfolio.total_value
            if new_portfolio.total_value > 0
            else 0.0
        )

        if position_pct > self.limits.max_position_pct:
            violations.append(
                f"position size {position_pct:.1%} exceeds limit {self.limits.max_position_pct:.1%}"
            )
        if sector_pct > self.limits.max_sector_pct:
            violations.append(
                f"sector {sector} exposure {sector_pct:.1%} exceeds limit {self.limits.max_sector_pct:.1%}"
            )
        if beta_exposure > self.limits.max_beta_weighted:
            violations.append(
                f"beta-weighted exposure {beta_exposure:.2f} exceeds limit {self.limits.max_beta_weighted:.2f}"
            )
        if var_pct > self.limits.max_var_95_pct:
            violations.append(
                f"VaR {var_pct:.1%} exceeds limit {self.limits.max_var_95_pct:.1%}"
            )
        if portfolio.current_drawdown > self.limits.max_drawdown_pct:
            violations.append(
                f"current drawdown {portfolio.current_drawdown:.1%} exceeds limit {self.limits.max_drawdown_pct:.1%}"
            )
        if new_portfolio.top5_concentration > self.limits.max_concentration_top5:
            violations.append(
                f"top-5 concentration {new_portfolio.top5_concentration:.1%} exceeds limit {self.limits.max_concentration_top5:.1%}"
            )
        if gross_leverage > self.limits.max_gross_leverage:
            violations.append(
                f"gross leverage {gross_leverage:.2f}x exceeds limit {self.limits.max_gross_leverage:.2f}x"
            )
        if net_exposure_pct > self.limits.max_net_exposure_pct:
            violations.append(
                f"net exposure {net_exposure_pct:.1%} exceeds limit {self.limits.max_net_exposure_pct:.1%}"
            )

        risk_metrics = {
            "position_pct": position_pct,
            "sector": sector,
            "sector_pct": sector_pct,
            "beta_exposure": beta_exposure,
            "var_pct": var_pct,
            "drawdown": portfolio.current_drawdown,
            "top5_concentration": new_portfolio.top5_concentration,
            "gross_leverage": gross_leverage,
            "net_exposure_pct": net_exposure_pct,
        }
        if violations:
            return {"allowed": False, "reason": "; ".join(violations), "risk_metrics": risk_metrics}
        return {"allowed": True, "reason": "all risk checks passed", "risk_metrics": risk_metrics}

    def get_portfolio(self) -> PortfolioRisk:
        """Public accessor for the current portfolio snapshot."""
        return self._get_portfolio_snapshot()

    # -- internals -----------------------------------------------------

    def _get_portfolio_snapshot(self) -> PortfolioRisk:
        """Read open positions from ``paper_trades`` and compute risk metrics."""
        if self._engine is None:
            # No DB - safe empty portfolio with base capital. Lets the
            # engine still answer ``check_trade_allowed`` in dev/test.
            return PortfolioRisk(total_value=self.base_capital)

        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT symbol, side, quantity, entry_price
                        FROM paper_trades
                        WHERE status = 'open' AND org_id = :org_id
                        """
                    ),
                    {"org_id": self.org_id},
                ).fetchall()
                realized_today = self._read_realized_pnl_today(conn)
                drawdown_pct = self._read_current_drawdown(conn)
        except Exception as exc:
            logger.warning("portfolio_snapshot_read_failed: %s", exc)
            return PortfolioRisk(total_value=self.base_capital)

        positions: list[PositionRisk] = []
        unrealized_pnl = 0.0
        for raw_symbol, raw_side, qty, entry in rows:
            symbol = (raw_symbol or "").upper()
            side = (raw_side or "").upper()
            shares = int(qty or 0)
            entry_price = float(entry or 0.0)
            if shares == 0 or entry_price <= 0:
                continue
            current_price = self._fetch_price(symbol, entry_price)
            signed_qty = shares if side == "BUY" else -shares
            market_value = signed_qty * current_price
            pnl = (current_price - entry_price) * signed_qty
            pnl_pct = (current_price / entry_price - 1.0) * 100.0 if entry_price > 0 else 0.0
            positions.append(
                PositionRisk(
                    symbol=symbol,
                    quantity=signed_qty,
                    entry_price=entry_price,
                    current_price=current_price,
                    market_value=market_value,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    beta=self._get_beta(symbol),
                    sector=self._get_sector(symbol),
                    position_pct=0.0,  # filled below
                )
            )
            unrealized_pnl += pnl

        # Equity = base capital + realized today + unrealized MTM. This is
        # always positive in normal conditions; it's the denominator we use
        # for *all* limit checks.
        total_value = max(1.0, self.base_capital + realized_today + unrealized_pnl)

        # Recompute per-position percentages now that we know total_value.
        for pos in positions:
            pos.position_pct = abs(pos.market_value) / total_value

        return self._compose_portfolio(
            positions=positions,
            total_value=total_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_today=realized_today,
            current_drawdown=drawdown_pct,
        )

    def _compose_portfolio(
        self,
        positions: list[PositionRisk],
        total_value: float,
        *,
        unrealized_pnl: float = 0.0,
        realized_pnl_today: float = 0.0,
        current_drawdown: float = 0.0,
    ) -> PortfolioRisk:
        gross_exposure = float(sum(abs(p.market_value) for p in positions))
        long_exposure = float(sum(p.market_value for p in positions if p.market_value > 0))
        short_exposure = float(sum(-p.market_value for p in positions if p.market_value < 0))
        net_exposure = long_exposure - short_exposure
        portfolio_beta = float(
            sum(p.beta * (p.market_value / total_value) for p in positions)
            if total_value > 0
            else 0.0
        )
        # Sector exposure as an *absolute* fraction of total value -
        # netting longs against shorts in a sector cap is a real-world
        # source of accidental concentration.
        sector_exposure: dict[str, float] = {}
        for pos in positions:
            sector_exposure[pos.sector] = sector_exposure.get(pos.sector, 0.0) + abs(pos.market_value)
        sector_exposure_pct = {
            sector: value / total_value if total_value > 0 else 0.0
            for sector, value in sector_exposure.items()
        }
        sorted_positions = sorted(positions, key=lambda p: abs(p.market_value), reverse=True)
        top5_value = float(sum(abs(p.market_value) for p in sorted_positions[:5]))
        top5_concentration = top5_value / total_value if total_value > 0 else 0.0
        return PortfolioRisk(
            total_value=total_value,
            positions=positions,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            long_exposure=long_exposure,
            short_exposure=short_exposure,
            sector_exposure=sector_exposure_pct,
            portfolio_beta=portfolio_beta,
            var_95=0.0,
            current_drawdown=current_drawdown,
            top5_concentration=top5_concentration,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_today=realized_pnl_today,
        )

    def _simulate_trade(
        self,
        portfolio: PortfolioRisk,
        symbol: str,
        signed_quantity: int,
        price: float,
    ) -> PortfolioRisk:
        """Return a hypothetical portfolio with the new trade applied."""
        positions = [PositionRisk(**p.__dict__) for p in portfolio.positions]
        market_value = signed_quantity * price
        positions.append(
            PositionRisk(
                symbol=symbol,
                quantity=signed_quantity,
                entry_price=price,
                current_price=price,
                market_value=market_value,
                pnl=0.0,
                pnl_pct=0.0,
                beta=self._get_beta(symbol),
                sector=self._get_sector(symbol),
                position_pct=abs(market_value) / portfolio.total_value if portfolio.total_value > 0 else 0.0,
            )
        )
        # Re-flow position_pct on the simulated set so the *aggregated*
        # exposure to a symbol is correct (the spec returned just the new
        # row's pct, missing existing exposure to the same symbol).
        for pos in positions:
            pos.position_pct = abs(pos.market_value) / portfolio.total_value if portfolio.total_value > 0 else 0.0
        return self._compose_portfolio(
            positions=positions,
            total_value=portfolio.total_value,
            unrealized_pnl=portfolio.unrealized_pnl,
            realized_pnl_today=portfolio.realized_pnl_today,
            current_drawdown=portfolio.current_drawdown,
        )

    def _symbol_exposure_pct(self, portfolio: PortfolioRisk, symbol: str) -> float:
        """Aggregate absolute exposure to ``symbol`` across all rows."""
        if portfolio.total_value <= 0:
            return 0.0
        target = (symbol or "").upper()
        gross = sum(abs(p.market_value) for p in portfolio.positions if p.symbol.upper() == target)
        return gross / portfolio.total_value

    def _calculate_var(self, portfolio: PortfolioRisk, confidence: float = 0.95) -> float:
        """Parametric VaR with a configurable inter-position correlation.

        Variance of a sum of correlated random variables:
        ``Var(sum) = sum(var_i) + 2 * sum_{i<j} cov(i,j)``. Assuming a
        constant pairwise correlation ``rho`` and identical per-position
        volatility ``sigma`` gives a closed form we can compute in O(n).
        """
        if not portfolio.positions:
            return 0.0
        sigma = self.position_volatility
        rho = self.position_correlation
        values = np.array([abs(p.market_value) for p in portfolio.positions], dtype=float)
        var_sum = float(np.sum((values * sigma) ** 2))
        # Cross-covariance term.
        s = float(values.sum())
        s2 = float((values ** 2).sum())
        cov_sum = rho * sigma * sigma * (s * s - s2)
        portfolio_variance = max(0.0, var_sum + cov_sum)
        portfolio_sigma = float(np.sqrt(portfolio_variance))
        z = self.z_score_99 if confidence >= 0.99 else self.z_score_95
        return z * portfolio_sigma

    def _calculate_beta_weighted_exposure(self, portfolio: PortfolioRisk) -> float:
        if portfolio.total_value <= 0:
            return 0.0
        return sum(p.beta * abs(p.market_value) / portfolio.total_value for p in portfolio.positions)

    def _get_sector(self, symbol: str) -> str:
        return self.sector_map.get((symbol or "").upper(), "Other")

    def _get_beta(self, symbol: str) -> float:
        return float(self.beta_map.get((symbol or "").upper(), 1.0))

    def _fetch_price(self, symbol: str, fallback: float) -> float:
        if self._price_provider is None:
            return float(fallback)
        try:
            price = float(self._price_provider(symbol) or 0.0)
        except Exception as exc:
            logger.debug("price_provider_failed symbol=%s: %s", symbol, exc)
            return float(fallback)
        return price if price > 0 else float(fallback)

    def _read_realized_pnl_today(self, conn: Any) -> float:
        try:
            row = conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(realized_pnl), 0)
                    FROM paper_trades
                    WHERE status = 'closed'
                      AND org_id = :org_id
                      AND closed_at >= :start_of_day
                    """
                ),
                {"org_id": self.org_id, "start_of_day": date.today()},
            ).first()
        except Exception as exc:
            logger.debug("realized_pnl_read_failed: %s", exc)
            return 0.0
        return float(row[0] or 0.0) if row else 0.0

    def _read_current_drawdown(self, conn: Any) -> float:
        """Estimate current drawdown from the running cumulative realized PnL.

        Real production should track an explicit equity curve table (with
        intraday MTM); this is a best-effort proxy until that table exists.
        """
        try:
            rows = conn.execute(
                text(
                    """
                    SELECT realized_pnl
                    FROM paper_trades
                    WHERE status = 'closed' AND org_id = :org_id
                    ORDER BY closed_at ASC
                    """
                ),
                {"org_id": self.org_id},
            ).fetchall()
        except Exception as exc:
            logger.debug("drawdown_read_failed: %s", exc)
            return 0.0
        if not rows:
            return 0.0
        pnls = np.array([float(r[0] or 0.0) for r in rows])
        equity = self.base_capital + np.cumsum(pnls)
        peak = np.maximum.accumulate(equity)
        # Avoid divide-by-zero when peak <= 0.
        peak_safe = np.where(peak > 0, peak, 1.0)
        drawdowns = (peak - equity) / peak_safe
        return float(np.max(drawdowns))


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------


_singleton: PortfolioRiskEngine | None = None
_singleton_lock = threading.Lock()


def get_portfolio_risk_engine() -> PortfolioRiskEngine:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = PortfolioRiskEngine()
    return _singleton


def reset_portfolio_risk_engine() -> None:
    """Test-only reset for the process-wide singleton."""
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "PortfolioRisk",
    "PortfolioRiskEngine",
    "PositionRisk",
    "RiskLimits",
    "get_portfolio_risk_engine",
    "reset_portfolio_risk_engine",
]
