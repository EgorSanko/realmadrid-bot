from datetime import datetime

from fastapi.testclient import TestClient

from app.main import VERSION, app

client = TestClient(app)


def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == VERSION
    # время в ISO 8601 и с часовым поясом
    assert datetime.fromisoformat(body["time"]).tzinfo is not None


def test_unknown_route_404():
    assert client.get("/api/nope").status_code == 404


def test_health_head():
    assert client.head("/api/health").status_code == 200
