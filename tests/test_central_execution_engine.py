from services.central_execution_engine import ExecutionContext, detect_intent, execute_command


def test_detect_intent_research_default() -> None:
    assert detect_intent("Find cheapest HDPE pipe supplier in India") == "research"


def test_detect_intent_business() -> None:
    assert detect_intent("Show business revenue and inventory status") == "business"


def test_detect_intent_personal() -> None:
    assert detect_intent("Add task prepare monthly plan") == "personal"


def test_detect_intent_money() -> None:
    assert detect_intent("Generate stock signal for INFY") == "money"


def test_execute_build_uses_real_website_builder(monkeypatch) -> None:
    def fake_build_website_sync(business_id, template_type, *, user_id=None, run_deploy=False):
        return {
            "ok": True,
            "business_id": business_id,
            "template_type": template_type,
            "run_deploy": run_deploy,
            "user_id": user_id,
        }

    monkeypatch.setattr(
        "services.modular_execution_services.build_website_sync",
        fake_build_website_sync,
    )

    out = execute_command(
        "Build landing page for organization 42 and deploy",
        ExecutionContext(user_id=7, organization_id=3, role_name="owner"),
    )

    assert out["intent"] == "build"
    assert out["status"] == "success"
    assert out["result"]["ok"] is True
    assert out["result"]["business_id"] == 42
    assert out["result"]["template_type"] == "landing"
    assert out["result"]["run_deploy"] is True
    assert out["result"]["user_id"] == 7
