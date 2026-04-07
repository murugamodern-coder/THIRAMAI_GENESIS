"""CLI smoke tests moved out of brain.py."""

from __future__ import annotations

from datetime import date

from core.database import get_database_url, ping_database
from core.observability import ensure_thiramai_logging, log_structured


def smoke_test_invoice_pdf() -> None:
    ensure_thiramai_logging()
    from factory.billing_tool import build_invoice_pdf, default_invoice_path

    inv_date = date.today().isoformat()
    out = default_invoice_path()
    p = build_invoice_pdf(
        buyer_name="Smoke Test",
        buyer_address="-",
        invoice_no=f"SMOKE-{inv_date.replace('-', '')}",
        invoice_date=inv_date,
        length_m=1.0,
        grade="HDPE",
        weight_kg=1.0,
        rate_per_kg=100.0,
        gst_percent=18.0,
        seller_name="THIRAMAI Smoke",
        seller_address="-",
        seller_gstin="-",
        out_path=out,
    )
    log_structured("system_checks.smoke_invoice_ok", path=str(p))


def run_full_system_check() -> int:
    ensure_thiramai_logging()
    errors: list[str] = []

    log_structured("system_checks.step", step=1, name="smoke_invoice_pdf")
    try:
        smoke_test_invoice_pdf()
    except Exception as exc:
        errors.append(f"smoke_invoice: {type(exc).__name__}: {exc}")

    log_structured("system_checks.step", step=2, name="market_watch")
    try:
        from factory import market_watch

        snap = market_watch.resin_price_snapshot()
        cal = str(snap.get("calendar_date") or "")
        if cal and cal != date.today().isoformat():
            errors.append(f"market_watch: calendar_date mismatch ({cal} vs {date.today().isoformat()})")
        if not isinstance(snap.get("hdpe_3m"), dict):
            errors.append("market_watch: missing hdpe_3m block")
        market_watch.procurement_alert_payload()
    except Exception as exc:
        errors.append(f"market_watch: {type(exc).__name__}: {exc}")

    log_structured("system_checks.step", step=3, name="financial_performance_summary")
    try:
        from services.financial_service import financial_performance_summary

        summary = financial_performance_summary()
        if not isinstance(summary.get("tsi"), dict):
            errors.append("financial_summary: missing tsi")
        elif summary["tsi"].get("score") is None:
            errors.append("financial_summary: tsi.score missing")
        cfr = summary.get("cash_flow_radar")
        if not isinstance(cfr, dict):
            errors.append("financial_summary: missing cash_flow_radar")
        elif "robotics_fund_inr" not in cfr:
            errors.append("financial_summary: cash_flow_radar missing robotics_fund_inr")
    except Exception as exc:
        errors.append(f"financial_summary: {type(exc).__name__}: {exc}")

    log_structured("system_checks.step", step=4, name="digital_twin_tick")
    try:
        from factory.machine_sensor import tick_and_get_live_status

        twin = tick_and_get_live_status()
        if not isinstance(twin.get("sensors"), dict):
            errors.append("digital_twin: missing sensors")
    except Exception as exc:
        errors.append(f"digital_twin: {type(exc).__name__}: {exc}")

    log_structured("system_checks.step", step=5, name="postgresql_ping")
    if not get_database_url():
        log_structured("system_checks.db_skip", reason="DATABASE_URL not set")
    else:
        ok, msg = ping_database()
        if not ok:
            errors.append(f"database: {msg}")

    if errors:
        for line in errors:
            log_structured("system_checks.error", detail=line)
        log_structured("system_checks.summary", ok=False, error_count=len(errors))
        return 1
    log_structured("system_checks.summary", ok=True, message="SOVEREIGN SYSTEM: ALL GREEN")
    return 0
