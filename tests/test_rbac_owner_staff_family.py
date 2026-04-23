from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import CurrentUser, get_current_user
from api.routes.business_module import router as business_router
from api.routes.execute import router as execute_router

app = FastAPI()
app.include_router(business_router)
app.include_router(execute_router)


def _principal(*, role_name: str, role_level: int) -> CurrentUser:
    return CurrentUser(
        id=101,
        email=f"{role_name}@test.local",
        organization_id=1,
        role_name=role_name,
        role_level=role_level,
        is_active=True,
    )


def _client_as(user: CurrentUser) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_owner_full_access_business_and_execute_money(monkeypatch) -> None:
    owner = _principal(role_name="owner", role_level=1)
    client = _client_as(owner)

    monkeypatch.setattr(
        "api.routes.business_module.list_inventory_items_sync",
        lambda organization_id, limit, offset: {
            "ok": True,
            "items": [{"id": 1, "external_ref": "business_module:user:999"}],
        },
    )
    monkeypatch.setattr(
        "services.modular_execution_services.generate_intraday_signal",
        lambda symbol, user_id: {"ok": True, "symbol": symbol, "user_id": user_id, "signal": "BUY"},
    )

    r_inventory = client.get("/business/inventory")
    assert r_inventory.status_code == 200
    assert r_inventory.json()["erp_summary"]["scope"] == "full"

    r_execute = client.post("/execute", json={"command": "Buy stock INFY now"})
    assert r_execute.status_code == 200
    body = r_execute.json()
    assert body["intent"] == "trading"
    assert body["status"] == "success"
    assert isinstance(body["steps"], list) and body["steps"]

    app.dependency_overrides.clear()


def test_staff_limited_business_access_and_blocked_for_money(monkeypatch) -> None:
    staff = _principal(role_name="staff", role_level=4)
    client = _client_as(staff)

    monkeypatch.setattr(
        "api.routes.business_module.list_inventory_items_sync",
        lambda organization_id, limit, offset: {
            "ok": True,
            "items": [
                {"id": 1, "external_ref": "business_module:user:101"},
                {"id": 2, "external_ref": "business_module:user:202"},
            ],
        },
    )

    r_inventory = client.get("/business/inventory")
    assert r_inventory.status_code == 200
    data = r_inventory.json()
    assert data["erp_summary"]["scope"] == "staff_own_data"
    assert len(data["inventory"]) == 1
    assert data["inventory"][0]["id"] == 1

    r_execute = client.post("/execute", json={"command": "Buy stock TCS"})
    assert r_execute.status_code == 403

    app.dependency_overrides.clear()


def test_family_personal_only_block_business() -> None:
    family = _principal(role_name="customer", role_level=5)
    client = _client_as(family)

    r_personal = client.post("/execute", json={"command": "Add task water plants at 7 pm"})
    assert r_personal.status_code == 200
    assert r_personal.json()["intent"] == "personal"

    r_business = client.get("/business/inventory")
    assert r_business.status_code == 403

    app.dependency_overrides.clear()
