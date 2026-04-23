from services.intent_classifier import classify_intent


def test_buy_stock_maps_to_money() -> None:
    assert classify_intent("Buy stock") == "money"


def test_find_supplier_maps_to_research() -> None:
    assert classify_intent("Find supplier") == "research"


def test_create_invoice_maps_to_business() -> None:
    assert classify_intent("Create invoice") == "business"


def test_personal_task_maps_to_personal() -> None:
    assert classify_intent("Add personal task for tomorrow") == "personal"


def test_build_prompt_maps_to_build() -> None:
    assert classify_intent("Build an automation tool for invoices") == "build"
