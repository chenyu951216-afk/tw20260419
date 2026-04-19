from __future__ import annotations

from fastapi.testclient import TestClient

from tw_stock_ai.main import app


def test_ui_pages_respond_successfully() -> None:
    client = TestClient(app)

    for path in ("/picks", "/treasures", "/holdings", "/settings", "/system"):
        response = client.get(path)
        assert response.status_code == 200
