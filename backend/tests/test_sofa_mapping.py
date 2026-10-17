"""Сопоставление календаря FotMob с SofaScore на весь сезон.

Данные — срез с сервера 17.10.2026 (календарь FotMob 47 матчей; team/2829/events last/0, next/0, next/1).
Раньше брали только next/0 — апрельские и майские туры (вторая страница) оставались без id SofaScore."""
import asyncio

from app import store
from app.collector import Collector
from app.sources.base import NotFound

from .conftest import load


def run(coro):
    return asyncio.run(coro)


PAGES = load("sofa_team_pages_20261017.json")
FIXTURES = load("fixtures_20261017.json")


def _collector(conn, monkeypatch, calls):
    c = Collector(conn)

    async def ss_fetch(url, params):
        calls.append(url)
        if url.endswith("/players"):
            return {"players": []}
        which, page = url.rsplit("/", 2)[-2:]
        key = f"{which}{page}"
        if key not in PAGES:
            raise NotFound(f"404 {url}")
        return PAGES[key]

    monkeypatch.setattr(c.ss, "_fetch", ss_fetch)
    return c


def test_team_events_reads_all_next_pages(tmp_db, monkeypatch):
    conn = store.connect()
    calls = []
    c = _collector(conn, monkeypatch, calls)
    evs = run(c._sofa_team_events())
    assert [u.rsplit("/events/", 1)[1] for u in calls] == ["last/0", "next/0", "next/1"]  # next/1: hasNextPage=False
    assert len(evs) == 30 + 30 + 7
    assert max(e["startTimestamp"] for e in evs) >= 1811548800  # 2027-05-30: последний тур
    run(c.close())


def test_mapping_covers_whole_season(tmp_db, monkeypatch):
    (tmp_db / "disabled_sources").write_text("espn")
    conn = store.connect()
    store.put(conn, "fixtures", "fotmob", FIXTURES)
    c = _collector(conn, monkeypatch, [])
    res = run(c.refresh_mapping())
    mapped = store.map_all(conn, "match", "sofascore")
    got = set(mapped.values())
    assert sum(str(f["id"]) in got for f in FIXTURES) == len(FIXTURES) == 47
    assert res["sofascore_events"] == 67
    by_fm = {}
    for sid, fid in mapped.items():
        by_fm.setdefault(fid, []).append(sid)
    assert all(len(v) == 1 for v in by_fm.values()), "у матча FotMob ровно один id SofaScore"
    # дальний тур с датой-заглушкой (14:00 у FotMob, 19:00 у SofaScore) — в Ла Лигу, а не в Суперкубок
    # с той же парой за 4 дня до него
    assert store.from_fotmob(conn, "match", "sofascore", 5868239) == "16462564"
    assert store.from_fotmob(conn, "match", "sofascore", 6019526) == "16425708"
    # «Real Racing Club» / «Racing Santander», время не совпало: команду узнали по id из ноябрьского матча
    assert store.from_fotmob(conn, "match", "sofascore", 5868368) == "16462610"
    # последний тур со второй страницы
    assert store.from_fotmob(conn, "match", "sofascore", 5868389) == "16462670"
    run(c.close())


def test_mapping_before_fix_saw_only_first_page(tmp_db):
    """Метрика «до»: только last/0 + next/0 — 40 из 47 (апрель–май на второй странице)."""
    conn = store.connect()
    c = Collector(conn)
    evs = PAGES["last0"]["events"] + PAGES["next0"]["events"]
    items = [(str(e["id"]), e["startTimestamp"], e["homeTeam"]["name"], e["awayTeam"]["name"],
              e["homeTeam"]["id"], e["awayTeam"]["id"], None) for e in evs]
    c._map_list(FIXTURES, "sofascore", items)
    got = set(store.map_all(conn, "match", "sofascore").values())
    assert sum(str(f["id"]) in got for f in FIXTURES) == 40
    run(c.close())
