"""Счётчик посещений без входа (app/visits.py): /api/visit, /api/admin/stats, миграция v6, очистка."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import cleanup, visits
from app.predictions import db

from .conftest import tma

DEV = "6f1c2a9e-3b7d-4e1a-9c2f-0a1b2c3d4e5f"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36"}


@pytest.fixture(autouse=True)
def _fresh_limiter():
    visits._limiter = None
    yield
    visits._limiter = None


def hit(client, device=DEV, platform="web", headers=None, **kw):
    return client.post("/api/visit", json={"device": device, "platform": platform, **kw},
                       headers={**UA, **(headers or {})})


def rows(svc, sql, *args):
    with svc.conn() as c:
        return [tuple(r) for r in c.execute(sql, args)]


# ---------- миграция ----------

def test_migration_v6_tables(svc):
    assert db.SCHEMA_VERSION == 6
    with svc.conn() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 6
        cols = {r[1] for r in c.execute("PRAGMA table_info(visitors)")}
        assert cols == {"device", "first_day", "last_day", "platform", "user_id"}
        cols = {r[1] for r in c.execute("PRAGMA table_info(visit_days)")}
        assert cols == {"day", "device", "platform"}
        with pytest.raises(Exception):
            c.execute("INSERT INTO visit_days VALUES ('2026-10-17', 'x', 'ios')")


# ---------- /api/visit ----------

def test_visit_counts_once_per_day_and_hashes(client, svc):
    r = hit(client)
    assert r.status_code == 200 and r.json() == {"ok": True, "counted": True}
    assert hit(client).json()["counted"] is False                     # повтор в тот же день
    v = rows(svc, "SELECT device, first_day, last_day, platform, user_id FROM visitors")
    assert len(v) == 1
    device, first, last, platform, uid = v[0]
    assert DEV not in device and len(device) == 64 and device == visits.device_hash(DEV)  # только хеш
    assert (first, last, platform, uid) == ("2026-10-17", "2026-10-17", "web", None)   # 22:00 МСК 17 окт
    assert rows(svc, "SELECT day, platform FROM visit_days") == [("2026-10-17", "web")]


def test_visit_day_is_moscow(client, svc, clock):
    hit(client)
    clock.set(datetime(2026, 10, 17, 21, 30, tzinfo=timezone.utc))   # 00:30 МСК 18 окт — уже новый день
    assert hit(client).json()["counted"] is True
    assert rows(svc, "SELECT first_day, last_day FROM visitors") == [("2026-10-17", "2026-10-18")]
    assert len(rows(svc, "SELECT * FROM visit_days")) == 2


def test_visit_salt_from_env(monkeypatch):
    a = visits.device_hash(DEV)
    monkeypatch.setenv("VISIT_SALT", "другая соль")
    assert visits.device_hash(DEV) != a


@pytest.mark.parametrize("body", [
    {"device": "short", "platform": "web"},
    {"device": "x" * 65, "platform": "web"},
    {"device": "<script>alert(1)</script>xxxx", "platform": "web"},
    {"device": 12345678901234567890, "platform": "web"},
    {"device": DEV, "platform": "ios"},
    {"device": DEV},
    {"platform": "web"},
])
def test_visit_validation(client, svc, body):
    r = client.post("/api/visit", json=body, headers=UA)
    assert r.status_code == 422 and r.json()["error"] == "validation"
    assert rows(svc, "SELECT * FROM visitors") == []


def test_visit_bad_json_and_size(client):
    assert client.post("/api/visit", content=b"[1,2]", headers=UA).status_code == 422
    assert client.post("/api/visit", content=b"not json", headers=UA).status_code == 422
    big = {"device": DEV, "platform": "web", "pad": "x" * 600}
    assert client.post("/api/visit", json=big, headers=UA).status_code == 413


def test_visit_bots_ignored(client, svc):
    for ua in ("Googlebot/2.1 (+http://www.google.com/bot.html)", "Mozilla/5.0 HeadlessChrome/120.0", ""):
        r = client.post("/api/visit", json={"device": DEV, "platform": "web"}, headers={"User-Agent": ua})
        assert r.status_code == 200 and r.json()["counted"] is False
    assert rows(svc, "SELECT * FROM visitors") == []


def test_visit_cross_site_rejected(client, svc):
    r = hit(client, headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert rows(svc, "SELECT * FROM visitors") == []


def test_visit_links_user(client, svc):
    hit(client, platform="tg")                                        # сначала аноним
    assert rows(svc, "SELECT user_id FROM visitors") == [(None,)]
    r = hit(client, platform="tg", headers=tma(42))                  # тот же день, уже с initData
    assert r.json()["counted"] is False
    assert rows(svc, "SELECT user_id FROM visitors") == [(42,)]
    assert rows(svc, "SELECT COUNT(*) FROM users") == [(0,)]          # счётчик пользователей не создаёт
    assert len(rows(svc, "SELECT * FROM visit_days")) == 1


def test_visit_invalid_auth_is_anonymous(client, svc):
    r = hit(client, headers={"Authorization": "Session s1.1.2.3.bad"})
    assert r.json()["counted"] is True
    assert rows(svc, "SELECT user_id FROM visitors") == [(None,)]


def test_visit_rate_limit_per_ip(client, svc):
    for _ in range(visits.VISIT_RATE[0]):
        assert hit(client, device=str(uuid.uuid4())).status_code == 200
    assert hit(client, device=str(uuid.uuid4())).status_code == 429
    assert hit(client).status_code in (200, 429)


def test_delete_account_unlinks_visitor(client, svc):
    client.post("/api/auth/telegram", json={"initData": tma(7)["Authorization"][4:]})
    hit(client, headers=tma(7))
    assert rows(svc, "SELECT user_id FROM visitors") == [(7,)]
    r = client.request("DELETE", "/api/auth/me", json={"confirm": True}, headers=tma(7))
    assert r.status_code == 200
    assert rows(svc, "SELECT user_id FROM visitors") == [(None,)]     # посещение осталось, связь — нет


# ---------- /api/admin/stats ----------

def test_stats_requires_admin(client, svc, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    assert client.get("/api/admin/stats").status_code == 401
    r = client.get("/api/admin/stats", headers=tma(2))
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    assert client.get("/api/admin/stats", headers=tma(1)).status_code == 200


def test_stats_aggregation(client, svc, clock, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    d0 = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
    a, b, c_, d = (str(uuid.uuid4()) for _ in range(4))
    clock.set(d0)                                                     # 15 окт: a (web), b (tg)
    hit(client, a, "web")
    hit(client, b, "tg")
    clock.set(d0 + timedelta(days=1))                                 # 16 окт: a снова, c (android)
    hit(client, a, "web")
    hit(client, c_, "android")
    client.post("/api/auth/telegram", json={"initData": tma(5)["Authorization"][4:]})  # новый пользователь 16 окт
    clock.set(d0 + timedelta(days=2))                                 # 17 окт: d (web)
    hit(client, d, "web")
    with svc.conn() as c:                                             # визит 60 дней назад — вне окна
        visits.record(c, visits.device_hash(str(uuid.uuid4())), "web", "2026-08-18", None)

    s = client.get("/api/admin/stats", headers=tma(1)).json()
    assert s["today"] == "2026-10-17" and s["tz"] == "Europe/Moscow"
    assert len(s["days"]) == 30 and s["days"][-1]["day"] == "2026-10-17" and s["days"][0]["day"] == "2026-09-18"
    by = {r["day"]: r for r in s["days"]}
    assert by["2026-10-15"]["new_visitors"] == 2 and by["2026-10-15"]["new_by_platform"] == {"tg": 1, "android": 0, "web": 1}
    assert by["2026-10-16"]["new_visitors"] == 1 and by["2026-10-16"]["active_visitors"] == 2
    assert by["2026-10-16"]["new_by_platform"]["android"] == 1 and by["2026-10-16"]["active_by_platform"]["web"] == 1
    assert by["2026-10-16"]["new_users"] == 1
    assert by["2026-10-17"]["new_visitors"] == 1
    t = s["totals"]
    assert t["visitors"] == 5 and t["visitors_by_platform"] == {"tg": 1, "android": 1, "web": 3}
    assert t["users"] == 1
    assert (t["new_1d"], t["new_7d"], t["new_30d"]) == (1, 4, 4)
    assert (t["active_1d"], t["active_7d"], t["active_30d"]) == (1, 4, 4)
    assert t["new_users_7d"] == 1 and t["linked_visitors"] == 0


def test_stats_excludes_review_user(client, svc, monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1")
    monkeypatch.setenv("REVIEW_USER_ID", "999")
    svc.upsert_user({"id": 999, "first_name": "RuStore Проверка"})
    svc.upsert_user({"id": 3, "first_name": "Человек"})
    t = client.get("/api/admin/stats", headers=tma(1)).json()["totals"]
    assert t["users"] == 1 and t["new_users_1d"] == 1


# ---------- очистка ----------

def test_cleanup_drops_old_visit_days(svc):
    now = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
    with svc.conn() as c:
        visits.record(c, "a" * 64, "web", "2025-09-01", None)   # 411 дней назад
        visits.record(c, "b" * 64, "web", "2025-09-20", None)   # 392 дня — остаётся
        res = cleanup.visit_days(c, now)
        assert res == {"visit_days": 1}
        assert [r[0] for r in c.execute("SELECT device FROM visit_days")] == ["b" * 64]
        assert c.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 2   # итог «всего людей» цел
