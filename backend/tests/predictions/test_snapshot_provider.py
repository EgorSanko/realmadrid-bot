"""SnapshotProvider на настоящих снимках: календарь и состав FotMob, Рома 3:4 Реал (6106274), Реал — Севилья
до начала (5868098, снимок с сервера 17.10.2026: ожидаемый состав, выбывшие)."""
import copy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.predictions import api
from app.predictions.provider import ProviderUnavailable
from app.predictions.snapshot_provider import SnapshotProvider, first_rm_scorer, regular_score
from app.sources import fotmob

from ..conftest import load
from .conftest import Clock, Mono, tma

MBAPPE, VINI, BELLINGHAM, COURTOIS, MILITAO = 701154, 846033, 1077894, 170323, 844415
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
SEVILLA_KO = datetime(2026, 10, 18, 19, 0, tzinfo=timezone.utc)
ROMA_KO = datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc)


@pytest.fixture()
def snaps(tmp_db):
    conn = store.connect()
    raw = load("fotmob_team_8633.json")
    store.put(conn, "fixtures", "fotmob", fotmob.normalize_fixtures(raw))
    store.put(conn, "team", "fotmob", fotmob.normalize_team(raw))
    store.put(conn, "match:6106274", "fotmob", fotmob.normalize_match(load("fotmob_match_6106274.json")))
    yield conn
    conn.close()


def prov(t: datetime = NOW) -> SnapshotProvider:
    return SnapshotProvider(clock=lambda: t.timestamp())


def ids(squad):
    return [p["id"] for p in squad]


def test_roma_real_finished(snaps):
    m = prov().get_match("6106274")
    assert m["kickoff_utc"] == "2026-10-14T19:00:00Z" and m["status"] == "finished"
    assert m["home"] == {"id": 8686, "name": "Roma"} and m["away"] == {"id": 8633, "name": "Real Madrid"}
    assert m["rm_is_home"] is False and m["score"] == {"home": 3, "away": 4}
    assert m["first_rm_scorer_player_id"] == MBAPPE  # 25′, первый гол Реала
    assert m["tournament"]["id"] == 42
    # объявленный состав: 11 в основе + 12 в запасе, только игроки Реала, нападающие первыми
    sq = m["rm_squad"]
    assert len(sq) == 23 and MBAPPE in ids(sq) and 553849 not in ids(sq)  # вратарь Ромы — нет
    assert [p["position"] for p in sq[:3]] == ["FW", "FW", "FW"] and all(p["starter"] for p in sq[:11])
    assert sq[10]["id"] == COURTOIS and sq[11]["starter"] is False


def test_pre_match_expected_lineup_then_squad(snaps):
    store.put(snaps, "match:5868098", "fotmob", load("snapshot_match_5868098.json"))
    m = prov().get_match("5868098")
    assert m["status"] == "scheduled" and m["score"] is None and m["first_rm_scorer_player_id"] is None
    assert m["rm_is_home"] is True and m["away"]["id"] == 8302 and m["kickoff_utc"] == "2026-10-18T19:00:00Z"
    sq = ids(m["rm_squad"])
    # ожидаемый состав — первым (форварды Диоманде и Мбаппе), дальше остальные из снимка команды
    assert sq[:2] == [1735453, MBAPPE] and sq.index(COURTOIS) == 10
    assert len(sq) == len(set(sq)) and len(sq) > 11
    # выбывшие на матч (Винисиус, Милитао) не предлагаются
    assert VINI not in sq and MILITAO not in sq


def test_without_match_snapshot_uses_team_squad(snaps):
    m = prov().get_match("5868098")
    team = store.get(snaps, "team")["data"]["squad"]
    healthy = {p["id"] for line in team.values() for p in line if not p.get("injured")}
    assert set(ids(m["rm_squad"])) == healthy
    assert m["rm_squad"][0]["position"] == "FW" and m["rm_squad"][-1]["position"] == "GK"


def test_upcoming_recent_order(snaps):
    p = prov()
    up = p.upcoming(3)
    assert [x["id"] for x in up][:1] == ["5868098"] and all(x["status"] == "scheduled" for x in up)
    rec = p.recent(3)
    assert rec[0]["id"] == "6106274" and rec[0]["score"] == {"home": 3, "away": 4}
    assert [x["status"] for x in rec] == ["finished"] * 3
    assert p.get_match("424242") is None
    # матч «идёт» — тоже ближайший; незавершённый с началом 5 ч назад — уже нет
    assert prov(SEVILLA_KO + timedelta(minutes=30)).upcoming(1)[0]["id"] == "5868098"
    assert prov(SEVILLA_KO + timedelta(hours=5)).upcoming(1)[0]["id"] != "5868098"


def test_no_snapshots_is_unavailable(tmp_db):
    p = prov()
    for call in (lambda: p.upcoming(5), lambda: p.recent(5), lambda: p.get_match("1")):
        with pytest.raises(ProviderUnavailable):
            call()


def _goal(minute, side, pid, own=False, shootout=False, score=None):
    return {"type": "goal", "minute": minute, "added": None, "side": side, "player": {"id": pid, "name": "x"},
            "own_goal": own, "penalty": shootout, "shootout": shootout, "score": score}


def test_own_goal_of_opponent_is_not_first_scorer(snaps):
    m = store.get(snaps, "match:6106274")["data"]
    # автогол игрока Ромы на 10′ (гол в пользу Реала) — бонусом не считается: первым остаётся Мбаппе
    m["events"].insert(0, _goal(10, "away", 588687, own=True, score=[0, 1]))
    store.put(snaps, "match:6106274", "fotmob", m)
    assert prov().get_match("6106274")["first_rm_scorer_player_id"] == MBAPPE
    # Реал забил только автоголом соперника — автора нет, бонус никому
    assert first_rm_scorer([_goal(10, "away", 588687, own=True)], "away") is None
    # гол Ромы и автогол Реала — на стороне соперника, к первому голу Реала отношения не имеют
    assert first_rm_scorer([_goal(5, "home", 276738, own=True), _goal(9, "away", VINI)], "away") == VINI
    # хронология, а не порядок в списке; добавленное время — после основной минуты
    ev = [_goal(45, "away", BELLINGHAM), _goal(45, "away", VINI), _goal(30, "home", 1)]
    ev[0]["added"] = 2
    assert first_rm_scorer(ev, "away") == VINI


def test_shootout_not_counted(snaps):
    m = store.get(snaps, "match:6106274")["data"]
    m2 = copy.deepcopy(m)
    m2["events"] += [_goal(120, "home", 1, shootout=True, score=[4, 4]), _goal(120, "away", MBAPPE, shootout=True,
                                                                             score=[4, 5])]
    m2["home"]["score"], m2["away"]["score"] = 4, 5  # источник сложил серию со счётом
    store.put(snaps, "match:6106274", "fotmob", m2)
    assert prov().get_match("6106274")["score"] == {"home": 3, "away": 4}
    assert regular_score(1, 1, [], "Pen") == {"home": 0, "away": 0}  # 0:0 после 120 минут, серия отдельно
    assert regular_score(2, 1, [], "AET") == {"home": 2, "away": 1}  # дополнительное время — считается


def test_status_mapping_and_freshness(snaps):
    m = store.get(snaps, "match:6106274")["data"]
    live = copy.deepcopy(m)
    live["status"] = {"state": "halftime", "live": True, "finished": False, "minute": 45, "added": None, "label": "HT"}
    live["events"] = [e for e in live["events"] if e["minute"] <= 45]
    live["home"]["score"], live["away"]["score"] = 1, 1
    store.put(snaps, "match:6106274", "fotmob", live, fetched_at=store.get(snaps, "fixtures")["fetched_at"] - 60)
    # календарь свежее и говорит «завершён» — «завершён» не откатываем
    assert prov().get_match("6106274")["status"] == "finished"
    fx = store.get(snaps, "fixtures")["data"]
    row = next(f for f in fx if f["id"] == 6106274)
    row["status"] = {"state": "live", "live": True, "finished": False, "minute": 30, "added": None, "label": "30'"}
    store.put(snaps, "fixtures", "fotmob", fx)
    store.put(snaps, "match:6106274", "fotmob", live)  # снимок матча свежее календаря
    g = prov().get_match("6106274")
    assert g["status"] == "live" and g["score"] == {"home": 1, "away": 1} and g["first_rm_scorer_player_id"] == MBAPPE
    live["status"]["state"] = "abandoned"
    store.put(snaps, "match:6106274", "fotmob", live)
    assert prov().get_match("6106274")["status"] == "cancelled"


@pytest.fixture()
def snap_client(snaps, env):
    clock = Clock(SEVILLA_KO - timedelta(days=1))
    svc = api.configure(provider=prov(clock.t), db_path=str(env / "predictions.db"), clock=clock,
                        bot_username="madridista_bot", rate_clock=Mono())
    store.put(snaps, "match:5868098", "fotmob", load("snapshot_match_5868098.json"))
    yield TestClient(app), svc, clock
    api._service = None


def test_api_matches_and_accept_on_snapshots(snap_client):
    c, _, _ = snap_client
    b = c.get("/api/predict/matches", headers=tma(77)).json()
    nxt = b["next"]
    assert nxt["id"] == "5868098" and nxt["accepting"] is True and nxt["rm_side"] == "home"
    assert nxt["home"]["name"] == "Real Madrid" and nxt["tournament"]["id"] == 87
    assert nxt["rm_squad"][1] == {"id": str(MBAPPE), "name": "Kylian Mbappé", "position": "FW", "number": 10,
                                  "starter": True}
    assert b["recent"][0]["id"] == "6106274" and b["recent"][0]["score"] == {"home": 3, "away": 4}
    r = c.put("/api/predict/matches/5868098", json={"home": 2, "away": 1, "first_scorer_id": MBAPPE}, headers=tma(77))
    assert r.status_code == 200 and r.json()["first_scorer_id"] == str(MBAPPE)
    r = c.put("/api/predict/matches/5868098", json={"home": 2, "away": 1, "first_scorer_id": VINI}, headers=tma(77))
    assert r.status_code == 422 and r.json()["error"] == "scorer_not_in_squad"


def test_settle_roma_from_snapshots(snap_client, snaps):
    c, svc, clock = snap_client
    # до матча в Риме: календарь ещё «не начался», снимка матча нет
    full = store.get(snaps, "match:6106274")["data"]
    fx = store.get(snaps, "fixtures")["data"]
    row = next(f for f in fx if f["id"] == 6106274)
    done_status, done_home, done_away = row["status"], dict(row["home"]), dict(row["away"])
    row["status"] = {"state": "scheduled", "live": False, "finished": False, "minute": None, "added": None,
                     "label": None}
    row["home"]["score"] = row["away"]["score"] = None
    store.put(snaps, "fixtures", "fotmob", fx)
    snaps.execute("DELETE FROM snapshots WHERE key='match:6106274'")
    svc.provider = prov(ROMA_KO - timedelta(hours=2))
    clock.set(ROMA_KO - timedelta(hours=2))
    assert c.put("/api/predict/matches/6106274", json={"home": 3, "away": 4, "first_scorer_id": MBAPPE},
                 headers=tma(1)).status_code == 200
    assert c.put("/api/predict/matches/6106274", json={"home": 1, "away": 2, "first_scorer_id": VINI},
                 headers=tma(2)).status_code == 200
    # матч сыгран: сборщик записал итог
    row["status"], row["home"], row["away"] = done_status, done_home, done_away
    store.put(snaps, "fixtures", "fotmob", fx)
    store.put(snaps, "match:6106274", "fotmob", full)
    clock.set(ROMA_KO + timedelta(hours=3))
    svc.provider = prov(clock.t)
    assert svc.settle("6106274")["result"] == "settled"
    lb = c.get("/api/predict/leaderboard?period=season", headers=tma(1)).json()
    assert [(r["points"], r["is_me"]) for r in lb["top"]] == [(7, True), (3, False)]  # 5+2 и разница мячей
