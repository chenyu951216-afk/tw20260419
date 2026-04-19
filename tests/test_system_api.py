from __future__ import annotations

from fastapi.testclient import TestClient

from tw_stock_ai.main import app


def test_system_costs_and_effective_settings_endpoints() -> None:
    client = TestClient(app)

    costs = client.get("/api/system/costs")
    settings = client.get("/api/settings/effective")

    assert costs.status_code == 200
    assert "monthly_budget_twd" in costs.json()
    assert settings.status_code == 200
    assert "sections" in settings.json()
