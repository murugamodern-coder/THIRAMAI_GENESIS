"""SRE-focused unit checks: auth hashing, billing GST, predictive empty paths."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core import auth as auth_core
from services import billing_service
from services import predictive_engine as pe


def test_hash_password_verify_roundtrip() -> None:
    try:
        h = auth_core.hash_password("sre-test-password-9")
    except Exception as exc:
        pytest.skip(f"bcrypt not usable on this runtime: {exc}")
    assert auth_core.verify_password("sre-test-password-9", h)
    assert not auth_core.verify_password("wrong", h)


def test_gst_breakdown_intra_state() -> None:
    r = billing_service.gst_breakdown(1000.0, 18.0, intra_state=True)
    assert r["subtotal_inr"] == 1000.0
    assert r["cgst_inr"] == r["sgst_inr"]
    assert abs(r["grand_total_inr"] - 1180.0) < 0.01


def test_gst_breakdown_inter_state_igst() -> None:
    r = billing_service.gst_breakdown(1000.0, 18.0, intra_state=False)
    assert r["igst_inr"] > 0
    assert r["cgst_inr"] == 0.0 and r["sgst_inr"] == 0.0


def test_predictive_forecast_numeric_no_data() -> None:
    out = pe._forecast_numeric([])
    assert out["method"] == "no_data"
    assert out["next_value"] == 0.0


def test_predictive_compute_forecasts_raises_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from core import database as db_mod

    db_mod.reset_engine_cache()
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        pe.compute_forecasts(organization_id=1)


def test_predictive_compute_forecasts_empty_db_rows_no_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """PostgreSQL-specific SQL is not executed here; empty query results must not crash."""
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result

    class _SessCtx:
        def __enter__(self) -> MagicMock:
            return session

        def __exit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(pe, "get_session_factory", lambda: lambda: _SessCtx())

    out = pe.compute_forecasts(organization_id=42)
    assert out["organization_id"] == 42
    assert out["data_quality"]["distinct_invoice_months"] == 0
    rev = out["revenue_inr"]
    assert rev["method"] in (
        "no_data",
        "moving_average",
        "blend_ma_linear_short",
        "blend_ma_linear",
    )
