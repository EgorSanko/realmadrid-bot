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


def test_health_build_collector_and_counts(tmp_db, monkeypatch):
    """Сборка (git sha), возраст сердцебиения сборщика, число пользователей и прогнозов — без персональных данных."""
    import time

    from app import main
    from app.predictions import api
    from app.predictions.provider import FakeProvider

    monkeypatch.setattr(main, "BUILD_SHA", "abc1234")
    monkeypatch.setitem(main._COUNTS, "value", None)
    (tmp_db / "hb").write_text(str(time.time() - 42))
    prev = api._service
    svc = api.configure(provider=FakeProvider(), db_path=str(tmp_db / "predictions.db"))
    try:
        svc.upsert_user({"id": 1, "first_name": "Секретное Имя", "username": "secret_nick"})
        svc.upsert_user({"id": 2, "first_name": "B"})
        body = client.get("/api/health").json()
        assert body["build"] == "abc1234"
        assert 40 <= body["collector"]["heartbeat_age_s"] <= 60 and body["collector"]["ok"] is True
        assert body["counts"] == {"users": 2, "predictions": 0}
        raw = client.get("/api/health").text
        assert "Секретное" not in raw and "secret_nick" not in raw
        # сердцебиение старше 5 минут — ok: false, но сам health отвечает 200 (живость API)
        (tmp_db / "hb").write_text(str(time.time() - 600))
        r = client.get("/api/health")
        assert r.status_code == 200 and r.json()["collector"]["ok"] is False
        (tmp_db / "hb").unlink()
        assert client.get("/api/health").json()["collector"] == {"heartbeat_age_s": None, "ok": False}
    finally:
        api._service = prev
        main._COUNTS.update(at=0.0, value=None)
