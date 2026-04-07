"""
Lightweight forecasts from historical invoices and production logs (numpy: MA + linear trend).

Scoped per ``organization_id``. Intended for Owner/Manager dashboards and council context
(``context_engine``) — not a substitute for formal FP&A.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy import text

from core.database import get_session_factory

# SQLi: all ``text()`` queries use bound parameters only (``:oid``) — see ``core.sql_security``.

# Cap history window for stability with sparse tenants.
_MAX_MONTHS = 36
_MA_WINDOW = 3


def _month_starts(from_month: date, n: int) -> list[date]:
    """``n`` calendar month starts ending at ``from_month`` (first day of month)."""
    out: list[date] = []
    y, m = from_month.year, from_month.month
    for _ in range(n):
        out.append(date(y, m, 1))
        if m == 1:
            y -= 1
            m = 12
        else:
            m -= 1
    out.reverse()
    return out


def _parse_month_key(row: Any) -> date | None:
    if row is None:
        return None
    if isinstance(row, datetime):
        return date(row.year, row.month, 1)
    if isinstance(row, date):
        return date(row.year, row.month, 1)
    return None


def _fetch_monthly_revenue(session: Any, *, organization_id: int) -> dict[date, float]:
    oid = int(organization_id)
    sql = text(
        """
        SELECT
            (date_trunc(
                'month',
                COALESCE(invoice_date::timestamptz, created_at)
            ))::date AS month_start,
            SUM(grand_total_inr)::double precision AS revenue_inr
        FROM invoices
        WHERE organization_id = :oid
        GROUP BY 1
        ORDER BY 1
        """
    )
    rows = session.execute(sql, {"oid": oid}).all()
    out: dict[date, float] = {}
    for mstart, rev in rows:
        mk = _parse_month_key(mstart)
        if mk is None:
            continue
        out[mk] = float(rev or 0.0)
    return out


def _fetch_monthly_production_index(session: Any, *, organization_id: int) -> dict[date, float]:
    """
    Monthly sum of throughput-style fields (material in + output). Serves as an
    **inventory / production load index**, not SKU-level BOM.
    """
    oid = int(organization_id)
    sql = text(
        """
        SELECT
            (date_trunc('month', pl.timestamp))::date AS month_start,
            SUM(
                COALESCE(pl.yield_out, 0)
                + COALESCE(pl.blocks_out, 0)
                + COALESCE(pl.raw_material_in, 0)
                + COALESCE(pl.cement_in, 0)
                + COALESCE(pl.sand_in, 0)
            )::double precision AS volume_index
        FROM production_logs pl
        INNER JOIN assets a ON a.id = pl.asset_id
        WHERE a.organization_id = :oid
        GROUP BY 1
        ORDER BY 1
        """
    )
    rows = session.execute(sql, {"oid": oid}).all()
    out: dict[date, float] = {}
    for mstart, vol in rows:
        mk = _parse_month_key(mstart)
        if mk is None:
            continue
        out[mk] = float(vol or 0.0)
    return out


def _series_for_window(months: list[date], by_month: dict[date, float]) -> tuple[list[str], list[float]]:
    labels = [d.isoformat()[:7] for d in months]
    values = [float(by_month.get(d, 0.0)) for d in months]
    return labels, values


def _forecast_numeric(values: list[float]) -> dict[str, Any]:
    """3-month moving average + degree-1 polyfit; blend when enough history."""
    n = len(values)
    if n == 0:
        return {
            "next_value": 0.0,
            "method": "no_data",
            "moving_average_next": 0.0,
            "linear_trend_next": 0.0,
        }
    y = np.array(values, dtype=np.float64)
    tail = min(_MA_WINDOW, n)
    ma_next = float(np.mean(y[-tail:]))

    if n < 2:
        return {
            "next_value": max(0.0, ma_next),
            "method": "moving_average",
            "moving_average_next": max(0.0, ma_next),
            "linear_trend_next": max(0.0, ma_next),
        }

    x = np.arange(n, dtype=np.float64)
    slope, intercept = np.polyfit(x, y, 1)
    lin_next = float(slope * n + intercept)

    if n >= 4:
        blend = 0.5 * ma_next + 0.5 * lin_next
        method = "blend_ma_linear"
    elif n >= 2:
        blend = 0.65 * ma_next + 0.35 * lin_next
        method = "blend_ma_linear_short"
    else:
        blend = ma_next
        method = "moving_average"

    next_val = max(0.0, float(blend))
    return {
        "next_value": next_val,
        "method": method,
        "moving_average_next": max(0.0, ma_next),
        "linear_trend_next": max(0.0, lin_next),
        "slope_per_month": float(slope),
    }


def _next_calendar_month(after: date) -> tuple[date, date]:
    """First and last day of the month after ``after`` (``after`` = any day in month M)."""
    y, m = after.year, after.month
    if m == 12:
        y2, m2 = y + 1, 1
    else:
        y2, m2 = y, m + 1
    start = date(y2, m2, 1)
    _, last = monthrange(y2, m2)
    end = date(y2, m2, last)
    return start, end


def compute_forecasts(*, organization_id: int) -> dict[str, Any]:
    """
    Build monthly series from DB and predict **next calendar month** revenue (INR) and
    production/inventory-load index from ``production_logs``.
    """
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not configured")

    today = datetime.now(timezone.utc).date()
    current_month_start = date(today.year, today.month, 1)

    with factory() as session:
        rev_by_m = _fetch_monthly_revenue(session, organization_id=int(organization_id))
        vol_by_m = _fetch_monthly_production_index(session, organization_id=int(organization_id))

    all_months = sorted(set(rev_by_m.keys()) | set(vol_by_m.keys()))
    if not all_months:
        months = _month_starts(current_month_start, min(6, _MAX_MONTHS))
    else:
        last_data = all_months[-1]
        window_end = max(last_data, current_month_start)
        months = _month_starts(window_end, _MAX_MONTHS)

    rev_labels, rev_vals = _series_for_window(months, rev_by_m)
    vol_labels, vol_vals = _series_for_window(months, vol_by_m)

    rev_fc = _forecast_numeric(rev_vals)
    vol_fc = _forecast_numeric(vol_vals)

    last_month = months[-1] if months else current_month_start
    next_start, next_end = _next_calendar_month(last_month)

    return {
        "organization_id": int(organization_id),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_next_month": {
            "start": next_start.isoformat(),
            "end": next_end.isoformat(),
            "label": next_start.strftime("%B %Y"),
        },
        "revenue_inr": {
            "historical_months": rev_labels,
            "values": rev_vals,
            "forecast_next_month_inr": round(rev_fc["next_value"], 2),
            "moving_average_next_inr": round(rev_fc["moving_average_next"], 2),
            "linear_trend_next_inr": round(rev_fc["linear_trend_next"], 2),
            "method": rev_fc["method"],
        },
        "production_inventory_index": {
            "description": (
                "Sum per month of yield_out + blocks_out + raw_material_in + cement_in + sand_in "
                "for org assets; use as relative load for stocking / capacity — not SKU-level."
            ),
            "historical_months": vol_labels,
            "values": vol_vals,
            "forecast_next_month_index": round(vol_fc["next_value"], 4),
            "moving_average_next": round(vol_fc["moving_average_next"], 4),
            "linear_trend_next": round(vol_fc["linear_trend_next"], 4),
            "method": vol_fc["method"],
        },
        "disclaimer": (
            "Heuristic model (moving average + linear regression on monthly buckets). "
            "Sparse or one-off invoices skew results; validate against pipeline and seasonality."
        ),
        "data_quality": {
            "distinct_invoice_months": len(rev_by_m),
            "distinct_production_months": len(vol_by_m),
            "window_months": len(months),
        },
    }


def format_forecast_prompt_block(*, organization_id: int, max_chars: int = 1100) -> str:
    """
    Compact markdown for the council / Owner brief (injected by ``context_engine``).
    """
    try:
        data = compute_forecasts(organization_id=int(organization_id))
    except RuntimeError:
        return ""
    except Exception:
        return ""

    tgt = data.get("target_next_month") or {}
    rev = data.get("revenue_inr") or {}
    prod = data.get("production_inventory_index") or {}
    dq = data.get("data_quality") or {}

    lines = [
        "## Empire forecast (statistical — proactive advice for Owner)",
        f"- **Next month target:** {tgt.get('label', '?')} ({tgt.get('start', '')} → {tgt.get('end', '')})",
        f"- **Predicted revenue (INR, next month):** ≈ **{rev.get('forecast_next_month_inr', 0):,.2f}** "
        f"(3-mo MA ≈ {rev.get('moving_average_next_inr', 0):,.2f}; linear trend ≈ {rev.get('linear_trend_next_inr', 0):,.2f}; method={rev.get('method', '')})",
        f"- **Predicted production / inventory-load index (next month):** ≈ **{prod.get('forecast_next_month_index', 0):,.2f}** "
        f"(MA {prod.get('moving_average_next', 0):,.2f}; trend {prod.get('linear_trend_next', 0):,.2f})",
        "- **CEO guidance:** If revenue trend lags MA, tighten collections and pipeline; if the production index rises faster than revenue, "
        "plan raw material and working capital ahead. Compare to vault run-rate and debts.",
        f"- **Data:** invoice months={dq.get('distinct_invoice_months', 0)}, production months={dq.get('distinct_production_months', 0)}, window={dq.get('window_months', 0)}.",
        f"_{data.get('disclaimer', '')}_",
    ]
    text = "\n".join(lines).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n[... clipped ...]"
