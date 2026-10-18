"""Сборщик заранее собирает снимки всех сыгранных матчей сезона и 3 ближайших — открываются мгновенно."""
import asyncio

import pytest

from app import collector as collector_mod
from app import config, store
from app.collector import Collector
from app.sources import fotmob

from .conftest import load


@pytest.fixture()
def c(tmp_db):
    conn = store.connect()
    fx = fotmob.normalize_fixtures(load("fotmob_team_8633.json"))
    store.put(conn, "fixtures", "fotmob", fx)
    col = Collector(conn)
    fetched = []

    async def fake_refresh(fid, live=False):
        fetched.append(fid)
        store.put(conn, f"match:{fid}", "fotmob", {"id": int(fid)})
        return {"source": "fotmob"}

    col.refresh_match = fake_refresh
    yield col, conn, fx, fetched
    asyncio.run(col.close())
    conn.close()


def test_backfill_ids_finished_first_then_three_upcoming(c):
    col, _, fx, _ = c
    done = [str(f["id"]) for f in fx if f["status"]["finished"]][::-1]
    upcoming = [str(f["id"]) for f in fx if not f["status"]["finished"]
                and f["status"]["state"] not in ("cancelled", "postponed")][:3]
    assert col.backfill_ids(0) == done + upcoming


def test_backfill_one_per_tick_and_stops_when_done(c, monkeypatch):
    col, conn, _, fetched = c
    monkeypatch.setattr(collector_mod, "BACKFILL_EVERY", 0.0)
    total = len(col.backfill_ids(0))
    for i in range(total + 3):
        asyncio.run(col.tick_backfill(1000.0 + i))
    assert len(fetched) == total            # каждый — ровно один раз
    assert len(set(fetched)) == total
    assert col.backfill_ids(0) == []        # всё собрано
    assert asyncio.run(col.tick_backfill(10_000.0)) is None


def test_live_does_not_wait_for_idle_due(c):
    """Окно открылось, а матч недавно обновлён в idle-режиме (срок через 30 мин) — лайв сразу."""
    col = c[0] if isinstance(c, tuple) else c
    col.match_due["5868098"] = 1000.0 + config.IDLE_MATCH_INTERVAL
    assert col.live_due("5868098", 1000.0)
    col.match_due["5868098"] = 1000.0 + config.LIVE_INTERVAL      # обычный лайв-срок — ждём его
    assert not col.live_due("5868098", 1000.0)
    assert col.live_due("5868098", 1000.0 + config.LIVE_INTERVAL)
    assert col.live_due("777", 1000.0)                            # ещё не обновляли
