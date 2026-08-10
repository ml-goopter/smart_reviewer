from fastapi.testclient import TestClient

from app.main import app


def test_health_is_reachable_at_the_api_prefix():
    """Routes carry the full /api prefix because nginx does not strip it;
    if that ever changes, every path in the API contract moves with it."""
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
