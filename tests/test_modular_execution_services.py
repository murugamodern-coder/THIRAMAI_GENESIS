from services.modular_execution_services import BuildService, ResearchService, ServiceExecutionContext


def _ctx() -> ServiceExecutionContext:
    return ServiceExecutionContext(user_id=1, organization_id=1, role_name="owner")


def test_build_service_structured_result() -> None:
    out = BuildService().execute("Build a supplier comparison app", _ctx())
    assert out["intent"] == "build"
    assert out["status"] == "success"
    assert isinstance(out["steps"], list) and out["steps"]
    assert isinstance(out["result"], dict)


def test_research_service_execute_shape() -> None:
    out = ResearchService().execute("Find solar suppliers", _ctx())
    assert out["intent"] == "research"
    assert out["status"] in {"success", "error"}
    assert isinstance(out["steps"], list)
    assert "result" in out
