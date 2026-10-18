"""API читает только снимки: форма ответов, возраст, stale, кэш-заголовки, отсутствие 500."""
import time

import pytest
from fastapi.testclient import TestClient

from app import store
from app.sources import espn, fotmob

from .conftest import load


@pytest.fixture()
def client(tmp_db):
    conn = store.connect()
    raw = load("fotmob_team_8633.json")
    store.put(conn, "fixtures", "fotmob", fotmob.normalize_fixtures(raw))
    store.put(conn, "tables", "fotmob", fotmob.normalize_tables(raw))
    store.put(conn, "team", "fotmob", fotmob.normalize_team(raw))
    store.put(conn, "match:6106274", "fotmob", fotmob.normalize_match(load("fotmob_match_6106274.json")))
    from app.main import app
    yield TestClient(app), conn
    conn.close()


def test_home(client):
    c, _ = client
    r = c.get("/api/home")
    assert r.status_code == 200
    b = r.json()
    assert b["source"] == "fotmob" and b["age_s"] < 5 and b["stale"] is False
    assert b["next"]["id"] == 5868098 and b["next"]["away"]["logo"] == "/img/team/8302.png"
    assert b["last"]["id"] == 6106274 and b["last"]["result"] == "W"
    assert b["last"]["venue"]["name"] == "Stadio Olimpico"
    assert len(b["form"]) == 5 and b["form"][0]["id"] == 6106274
    assert b["laliga"]["pos"] == 4 and b["laliga"]["pts"]
    assert r.headers["cache-control"] == "public, max-age=30"


def test_match_and_stale_snapshot(client):
    c, conn = client
    r = c.get("/api/match/6106274")
    b = r.json()
    assert r.status_code == 200 and b["source"] == "fotmob" and "ratings" in b["available"]
    assert r.headers["cache-control"] == "public, max-age=60"
    # снимок двухчасовой давности (все источники лежат) — всё равно 200, с возрастом и stale
    old = store.get(conn, "match:6106274")
    store.put(conn, "match:6106274", "espn", espn.normalize_match(load("espn_summary_401915414.json"),
                                                                  {"match_id": 6106274}),
              fetched_at=time.time() - 7200)
    b = c.get("/api/match/6106274").json()
    assert b["source"] == "espn" and b["age_s"] >= 7199 and b["stale"] is True
    assert "ratings" not in b["available"]
    store.put(conn, "match:6106274", old["source"], old["data"])


def test_match_live_cache_header(client):
    c, conn = client
    m = store.get(conn, "match:6106274")["data"]
    m["status"] = {"state": "live", "live": True, "finished": False, "minute": 67, "added": None, "label": "67'"}
    store.put(conn, "match:999", "fotmob", m)
    r = c.get("/api/match/999")
    assert r.headers["cache-control"] == "public, max-age=5" and r.json()["status"]["minute"] == 67


def test_match_known_fixture_without_snapshot_asks_collector(client):
    c, conn = client
    r = c.get("/api/match/5868098")
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["available"] == []
    assert store.take_demand(conn) == ["5868098"]
    assert c.get("/api/match/123").status_code == 404


def test_fixtures_tables_team(client):
    c, _ = client
    f = c.get("/api/fixtures").json()
    assert f["tournaments"] == {"LaLiga": 38, "Champions League": 8, "Super Cup": 1}
    t = c.get("/api/tables").json()
    assert [x["league"]["id"] for x in t["tables"]] == [87, 42]
    tm = c.get("/api/team").json()
    assert tm["squad"]["goalkeepers"] and tm["squad"]["goalkeepers"][0]["photo"].startswith("/img/player/")
    assert "transfers" in tm["available"]


def test_health_sources_and_cold_start(tmp_db):
    from app.main import app
    c = TestClient(app)
    assert c.get("/api/home").status_code == 503  # пустая база: честно «нет данных», не 500
    conn = store.connect()
    store.put_source_state(conn, "fotmob", {"name": "fotmob", "requests": 5, "last_ok": time.time(), "last_error": None})
    b = c.get("/api/health/sources").json()
    assert b["sources"][0]["name"] == "fotmob" and b["sources"][0]["requests"] == 5
    assert c.get("/api/health/sources").headers["cache-control"] == "no-store"


def test_fixtures_take_live_status_from_match_snapshot(client):
    """Календарь обновляется раз в 12 мин — идущий матч берёт статус и счёт из своего лайв-снимка."""
    c, conn = client
    fx = store.get(conn, "fixtures")["data"]
    f = next(x for x in fx if x["id"] == 5868098)
    f["kickoff"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 20 * 60))
    store.put(conn, "fixtures", "fotmob", fx)
    m = store.get(conn, "match:6106274")["data"]
    m["status"] = {"state": "live", "live": True, "finished": False, "minute": 21, "added": None, "label": "21'"}
    m["home"] = {**m["home"], "score": 1}
    m["away"] = {**m["away"], "score": 0}
    store.put(conn, "match:5868098", "fotmob", m)
    r = c.get("/api/fixtures")
    row = next(x for x in r.json()["matches"] if x["id"] == 5868098)
    assert row["status"]["live"] and row["status"]["minute"] == 21
    assert row["home"]["score"] == 1 and row["away"]["score"] == 0
    assert row["home"]["name"] == f["home"]["name"]          # остальное — из календаря
    assert r.headers["cache-control"] == "public, max-age=5"
    # прошлый матч далеко от «сейчас» — как в календаре, снимок не подмешиваем
    old = next(x for x in r.json()["matches"] if x["id"] == 6106274)
    assert old["status"] == next(x for x in fx if x["id"] == 6106274)["status"]
