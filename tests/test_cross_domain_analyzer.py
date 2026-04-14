"""Cross-domain analyzer: cash stress, business spread, risk chain."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from core.db.models import Organization
from services.cross_domain_analyzer import analyze_cross_domain


def _session_cm(session):
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = None
    return MagicMock(return_value=cm)


@patch("services.cross_domain_analyzer.get_portfolio_summary_sync")
@patch("services.cross_domain_analyzer.daily_equity_pnl_inr_sync")
@patch("services.cross_domain_analyzer.get_business_margin")
@patch("services.cross_domain_analyzer.get_session_factory")
def test_negative_cash_flow(mock_sf, mock_bm, mock_daily, mock_port, monkeypatch):
    monkeypatch.delenv("THIRAMAI_CROSS_DOMAIN_MONTHLY_INCOME_INR", raising=False)
    sess = MagicMock()

    def se_get(model, oid):
        if model is Organization:
            m = MagicMock()
            m.name = "Solo Org"
            m.is_disabled = False
            return m
        return None

    sess.get.side_effect = se_get
    mock_sf.return_value = _session_cm(sess)

    mock_bm.return_value = {
        "ok": True,
        "organization_id": 1,
        "gross_margin_pct": 10.0,
        "net_profit_inr": "0",
        "operational_expenses_inr": "5000",
        "revenue_inr": "10000",
    }
    mock_daily.return_value = Decimal("-1000")
    mock_port.return_value = {"ok": True, "total_pnl_inr": "0", "positions": []}
    fin = {"spent_month": "25000", "spent_today": "0", "currency": "INR", "upcoming_emis": []}

    with patch("services.cross_domain_analyzer._active_org_ids", return_value=[1]), patch(
        "services.cross_domain_analyzer._total_monthly_emi", return_value=Decimal("40000")
    ), patch("services.cross_domain_analyzer._research_recent_count", return_value=0), patch(
        "services.cross_domain_analyzer._monthly_income_proxy", return_value=Decimal("50000")
    ):
        out = analyze_cross_domain(1, organization_id=1, financial_snapshot=fin)

    assert out["ok"] is True
    assert Decimal(str(out["metrics"]["available_cash_proxy_inr"])) < 0
    ids = {x["id"] for x in out["top_insights"]}
    assert "cash_crisis" in ids
    assert any("Cash crisis" in r for r in out["risk_alerts"])
    assert any("trading" in r.lower() for r in out["recommendations"])


@patch("services.cross_domain_analyzer.get_portfolio_summary_sync")
@patch("services.cross_domain_analyzer.daily_equity_pnl_inr_sync")
@patch("services.cross_domain_analyzer.get_business_margin")
@patch("services.cross_domain_analyzer.get_session_factory")
def test_business_comparison(mock_sf, mock_bm, mock_daily, mock_port, monkeypatch):
    monkeypatch.delenv("THIRAMAI_CROSS_DOMAIN_MONTHLY_INCOME_INR", raising=False)
    sess = MagicMock()

    def se_get(model, oid):
        if model is Organization:
            m = MagicMock()
            m.name = "Alpha" if oid == 1 else "Beta"
            m.is_disabled = False
            return m
        return None

    sess.get.side_effect = se_get
    mock_sf.return_value = _session_cm(sess)

    def bm_side(oid):
        if int(oid) == 1:
            return {
                "ok": True,
                "organization_id": 1,
                "gross_margin_pct": 18.0,
                "net_profit_inr": "100",
                "operational_expenses_inr": "500",
                "revenue_inr": "8000",
            }
        return {
            "ok": True,
            "organization_id": 2,
            "gross_margin_pct": 4.0,
            "net_profit_inr": "20",
            "operational_expenses_inr": "400",
            "revenue_inr": "2000",
        }

    mock_bm.side_effect = bm_side
    mock_daily.return_value = Decimal("0")
    mock_port.return_value = {"ok": True, "total_pnl_inr": "100", "positions": []}
    fin = {"spent_month": "1000", "spent_today": "50", "currency": "INR", "upcoming_emis": []}

    with patch("services.cross_domain_analyzer._active_org_ids", return_value=[1, 2]), patch(
        "services.cross_domain_analyzer._total_monthly_emi", return_value=Decimal("5000")
    ), patch("services.cross_domain_analyzer._research_recent_count", return_value=0), patch(
        "services.cross_domain_analyzer._monthly_income_proxy", return_value=Decimal("100000")
    ):
        out = analyze_cross_domain(1, organization_id=1, financial_snapshot=fin)

    assert out["ok"] is True
    assert any(x.get("id") == "business_spread" for x in out["top_insights"])


@patch("services.cross_domain_analyzer.get_portfolio_summary_sync")
@patch("services.cross_domain_analyzer.daily_equity_pnl_inr_sync")
@patch("services.cross_domain_analyzer.get_business_margin")
@patch("services.cross_domain_analyzer.get_session_factory")
def test_risk_chain_detection(mock_sf, mock_bm, mock_daily, mock_port, monkeypatch):
    monkeypatch.delenv("THIRAMAI_CROSS_DOMAIN_MONTHLY_INCOME_INR", raising=False)
    sess = MagicMock()

    def se_get(model, oid):
        if model is Organization:
            m = MagicMock()
            m.name = "Biz"
            m.is_disabled = False
            return m
        return None

    sess.get.side_effect = se_get
    mock_sf.return_value = _session_cm(sess)
    mock_bm.return_value = {
        "ok": True,
        "organization_id": 1,
        "gross_margin_pct": 8.0,
        "net_profit_inr": "-500",
        "operational_expenses_inr": "2000",
        "revenue_inr": "1000",
    }
    mock_daily.return_value = Decimal("-800")
    mock_port.return_value = {"ok": True, "total_pnl_inr": "-100", "positions": [{"symbol": "X"}]}
    due_soon = (date.today() + timedelta(days=3)).isoformat()
    fin = {
        "spent_month": "30000",
        "spent_today": "0",
        "currency": "INR",
        "upcoming_emis": [{"name": "Home", "due": due_soon, "emi": "10000"}],
    }
    with patch("services.cross_domain_analyzer._active_org_ids", return_value=[1]), patch(
        "services.cross_domain_analyzer._total_monthly_emi", return_value=Decimal("15000")
    ), patch("services.cross_domain_analyzer._research_recent_count", return_value=0), patch(
        "services.cross_domain_analyzer._monthly_income_proxy", return_value=Decimal("100000")
    ):
        out = analyze_cross_domain(1, organization_id=1, financial_snapshot=fin)

    assert out["ok"] is True
    assert out.get("chain_risk") is True
    assert any(x.get("id") == "risk_cascade" for x in out["top_insights"])


def test_invalid_user():
    out = analyze_cross_domain(0)
    assert out["ok"] is False


@patch("services.cross_domain_analyzer.get_session_factory", return_value=None)
def test_database_unconfigured(_):
    out = analyze_cross_domain(1, organization_id=1, financial_snapshot={"spent_month": "0", "upcoming_emis": []})
    assert out["ok"] is False
    assert out.get("error") == "database not configured"
