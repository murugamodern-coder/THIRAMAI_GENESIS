from services.research_engine_service import run_supplier_research_sync


def test_supplier_research_requires_query() -> None:
    out = run_supplier_research_sync("")
    assert out["ok"] is False
    assert "query required" in str(out.get("error") or "").lower()


def test_supplier_research_output_shape_when_search_fails(monkeypatch) -> None:
    def _mock_search(_query: str, *, max_results: int = 12):
        return {"ok": False, "error": "missing tavily key"}

    monkeypatch.setattr("services.research_engine_service.tavily_search_sync", _mock_search)
    out = run_supplier_research_sync("Find HDPE pipe coupler suppliers in Tamil Nadu")
    assert out["ok"] is False
    assert isinstance(out.get("suppliers"), list)
    assert isinstance(out.get("links"), list)

