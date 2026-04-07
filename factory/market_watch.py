"""
Simulated HDPE / LLDPE resin price tracker (Reliance / Exxon style curves).

90-day window for **3-month relative low** detection → dashboard **Procurement Alert**.
No live commodity API (deterministic simulation from calendar).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "factory_output" / ".market_watch_state.json"


def _day_seed(d: date) -> int:
    h = hashlib.sha256(d.isoformat().encode()).hexdigest()
    return int(h[:12], 16)


def _smooth_base_inr_per_kg(*, material: str, d: date) -> float:
    """Deterministic daily base INR/kg (illustrative — mimics trend noise)."""
    seed = _day_seed(d) + sum(ord(c) for c in material)
    span = 16.0
    base = 102.0 if material == "HDPE" else 98.0
    jitter = (seed % 1000) / 1000.0 * span
    return round(base + jitter, 2)


def _hdpe_series_days(*, end: date, days: int) -> list[float]:
    return [_smooth_base_inr_per_kg(material="HDPE", d=end - timedelta(days=i)) for i in range(days)]


def _hdpe_3m_stats(*, as_of: date) -> dict[str, object]:
    """~90 calendar days lookback; detect if today is near the trough (procurement signal)."""
    prices = _hdpe_series_days(end=as_of, days=90)
    if not prices:
        return {"at_3m_low": False}
    lo = min(prices)
    hi = max(prices)
    today = prices[0]
    # Days strictly cheaper than today → low ratio means today is near the 90d floor
    strictly_cheaper = sum(1 for p in prices if p < today - 1e-6)
    cheaper_ratio = strictly_cheaper / len(prices)
    near_floor = today <= lo + 0.4
    at_low = near_floor or cheaper_ratio <= 0.12
    return {
        "window_days": len(prices),
        "min_inr_per_kg": round(lo, 2),
        "max_inr_per_kg": round(hi, 2),
        "today_inr_per_kg": today,
        "at_3m_low": at_low,
        "cheaper_days_ratio_pct": round(100.0 * cheaper_ratio, 1),
        "near_floor_inr": near_floor,
    }


def _rd_protoresin_window_favourable(h3: dict[str, object], hdpe_inr: float) -> bool:
    """True when tape is at 3m low or today sits in the cheapest ~15% of the 90d band."""
    if not h3:
        return False
    if bool(h3.get("at_3m_low")):
        return True
    lo = float(h3.get("min_inr_per_kg") or 0)
    hi = float(h3.get("max_inr_per_kg") or 0)
    today = float(h3.get("today_inr_per_kg") or hdpe_inr)
    if hi <= lo:
        return False
    return today <= lo + 0.15 * (hi - lo)


def resin_price_snapshot(as_of: date | None = None) -> dict[str, object]:
    """
    Simulated spot quotes + WoW + 90d HDPE context for predictive UI.

    **Calendar anchor:** uses the **host system date** (`datetime.date.today()`), e.g. 2026-03-31,
    so the 90-day window rolls with the machine clock — aligned with dashboard “today”.
    Pass `as_of` only for tests or replays.
    """
    d = as_of or date.today()
    prev = d - timedelta(days=7)
    hdpe_today = _smooth_base_inr_per_kg(material="HDPE", d=d)
    hdpe_prev = _smooth_base_inr_per_kg(material="HDPE", d=prev)
    lldpe_today = _smooth_base_inr_per_kg(material="LLDPE", d=d)
    lldpe_prev = _smooth_base_inr_per_kg(material="LLDPE", d=prev)

    def wow(cur: float, old: float) -> float:
        if old <= 0:
            return 0.0
        return round(100.0 * (cur - old) / old, 2)

    wow_h = wow(hdpe_today, hdpe_prev)
    wow_l = wow(lldpe_today, lldpe_prev)
    h3 = _hdpe_3m_stats(as_of=d)

    out: dict[str, object] = {
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "calendar_date": d.isoformat(),
        "disclaimer": "Simulated indices for planning — not executable quotes.",
        "hdpe": {
            "inr_per_kg": hdpe_today,
            "wow_change_pct": wow_h,
            "label": "HDPE (pipe grade — Reliance / regional ref. curve)",
        },
        "lldpe": {
            "inr_per_kg": lldpe_today,
            "wow_change_pct": wow_l,
            "label": "LLDPE (film / blend ref. — Exxon-style curve proxy)",
        },
        "hdpe_3m": h3,
    }
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except OSError:
        pass
    return out


def procurement_alert_payload() -> dict[str, object]:
    """Dashboard + brief: highlight when simulated HDPE is at a 3-month relative low."""
    s = resin_price_snapshot()
    h3 = s.get("hdpe_3m") if isinstance(s.get("hdpe_3m"), dict) else {}
    active = bool(h3.get("at_3m_low"))
    today_p = h3.get("today_inr_per_kg")
    lo_p = h3.get("min_inr_per_kg")
    hi_p = h3.get("max_inr_per_kg")
    hd = s.get("hdpe") if isinstance(s.get("hdpe"), dict) else {}
    hdpe_inr = float(hd.get("inr_per_kg") or today_p or 0)
    rd_favourable = _rd_protoresin_window_favourable(h3, hdpe_inr)
    rd_note = ""
    if rd_favourable:
        rd_note = (
            "R&D: simulated HDPE is **favourable** — consider an extra **prototype / trial MOQ** "
            "(separate batch or colour from pipe-grade stock) for **robotics 3D printing**."
        )
    detail_active = (
        f"Simulated HDPE ~₹{today_p}/kg sits near the **90-day floor** (range ₹{lo_p}–₹{hi_p}/kg). "
        f"**Stock for extrusion** and, if vault R&D is active, a **dedicated prototyping sleeve**. "
        "Verify with your distributor."
    )
    detail_idle = "No 3-month low signal today (simulated curve)."
    detail = detail_active if active else detail_idle
    if rd_note:
        detail = f"{detail} {rd_note}"
    return {
        "active": active,
        "headline": "Procurement Alert" if active else "",
        "message": (
            "Sovereign Leader, resin price at 90-day low. Strategic buy recommended for both Pipe Stock and Humanoid Prototype R&D."
            if active
            else ""
        ),
        "detail": detail.strip(),
        "rd_protoresin_suggestion": rd_favourable,
        "rd_protoresin_note": rd_note,
    }


def procurement_advice_markdown() -> str:
    """Morning brief block: WoW tape + optional 3-month low callout."""
    s = resin_price_snapshot()
    hd = s["hdpe"] if isinstance(s.get("hdpe"), dict) else {}
    ll = s["lldpe"] if isinstance(s.get("lldpe"), dict) else {}
    h_pct = float(hd.get("wow_change_pct") or 0)
    l_pct = float(ll.get("wow_change_pct") or 0)
    h_inr = float(hd.get("inr_per_kg") or 0)
    l_inr = float(ll.get("inr_per_kg") or 0)
    h3 = s.get("hdpe_3m") if isinstance(s.get("hdpe_3m"), dict) else {}

    parts = [
        f"Sovereign Leader, **simulated resin tape** (planning only): **HDPE** ~**₹{h_inr:.2f}/kg** "
        f"({h_pct:+.1f}% WoW), **LLDPE** ~**₹{l_inr:.2f}/kg** ({l_pct:+.1f}% WoW)."
    ]
    if h3.get("at_3m_low"):
        parts.append(
            "**Predictive signal:** HDPE is at a **90-day relative low** — **Procurement Alert:** prioritize **Phase 2** resin stocking after cash guardrails check; "
            "optionally add a **small separate MOQ for R&D / humanoid prototyping** (non-potable batch)."
        )
    elif _rd_protoresin_window_favourable(h3, h_inr):
        parts.append(
            "**R&D procurement:** Simulated HDPE sits in a **favourable band** vs the 90-day range — good window to **quote extra trial resin** for **3D-print robotics** beyond factory pipe stock."
        )
    if h_pct <= -1.5 and l_pct <= -1.5:
        parts.append(
            "Both markers are **soft week-on-week** — a **constructive window** to **lock quotes** on raw material."
        )
    elif h_pct <= -1.0 or l_pct <= -1.0:
        parts.append(
            "At least one marker is **down ≥1% WoW** — **good time to compare offers** and float a **trial PO** if tank space and cash guardrails allow."
        )
    elif h_pct >= 1.5 or l_pct >= 1.5:
        parts.append(
            "**Upside pressure** on simulated curves — favor **consumption-first** and **defer discretionary bulk** unless a firm customer order covers the float."
        )
    elif not h3.get("at_3m_low"):
        parts.append(
            "Tape is **range-bound** — stay **disciplined on MOQ** and align buys with **confirmed extrusion runs** once the line is green."
        )
    parts.append("_Source: `factory/market_watch.py` (simulated; verify with live supplier quotes)._")
    return " ".join(parts)


def main() -> None:
    import pprint

    pprint.pprint(resin_price_snapshot())
    print()
    print(procurement_alert_payload())
    print()
    print(procurement_advice_markdown())


if __name__ == "__main__":
    main()
