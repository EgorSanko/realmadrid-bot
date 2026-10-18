"""Экран матча, новые блоки: «О матче» (стадион, погода, судья), расширенная статистика и зоны атак —
нормализаторы на сырых ответах FotMob (fixtures), смена источника и отсутствие данных."""
import time

from app.collector import borrow_static_blocks
from app.model import STAT_CATALOG, status
from app.sources import espn, fotmob, sofascore

from .conftest import load, sofa_bundle


def _live_raw():
    return load("fotmob_match_5868098_live.json")


# ================= нормализаторы =================

def test_info_box_venue_weather_referee():
    m = fotmob.normalize_match(_live_raw())
    assert m["venue"] == {"name": "Estadio Bernabéu", "city": "Madrid", "country": "Spain",
                          "flag": "/img/flag/es.svg", "capacity": 83186, "surface": "grass"}
    # ветер не берём — единицы в ответе не указаны
    assert m["weather"] == {"temp": 10, "key": "weather_condition_cloudy", "text": "Cloudy", "humidity": 78,
                            "cloud": 92, "precip": 0, "icon": 26, "at": "2026-10-18T20:00:00Z"}
    ri = m["referee_info"]
    assert m["referee"] == "Mateo Busquets Ferrer" and m["referee_country"]["flag"] == "/img/flag/es.svg"
    assert ri["id"] == 1001070988 and ri["photo"] == "/img/player/1001070988.png"
    assert ri["matches"] == 37 and ri["red"] == 8 and ri["pens"] == 10
    assert ri["league"] == {"id": 87, "name": "LaLiga"}
    assert ri["yellow"] == {"per_match": 5.51, "avg": 4.46, "total": 204, "level": "above", "fill": 100, "avg_fill": 50}
    assert ri["fouls"]["level"] == "average" and ri["fouls"]["avg"] == 24.99 and ri["fouls"]["fill"] == 44.88
    assert {"venue_details", "weather", "referee_stats", "zones"} <= set(m["available"])


def test_referee_without_stats_and_missing_blocks():
    raw = _live_raw()
    info = raw["content"]["matchFacts"]["infoBox"]
    info["Referee"] = {"text": "Some Ref", "country": "Spain", "countryCode": "ESP"}
    info["Stadium"] = {"name": "Estadio Bernabéu", "city": "Madrid", "country": "Spain"}
    raw["content"].pop("weather")
    raw["content"].pop("attackingZones")
    m = fotmob.normalize_match(raw)
    assert m["referee"] == "Some Ref" and m["referee_info"] is None
    assert "capacity" not in m["venue"] and m["weather"] is None and m["zones"] is None
    assert not {"venue_details", "weather", "referee_stats", "zones"} & set(m["available"])


def test_full_stats_37_keys_with_percentages():
    m = fotmob.normalize_match(_live_raw())
    keys = [x["key"] for x in m["stats"]["all"]]
    assert len(keys) == 37 == len(STAT_CATALOG) and len(set(keys)) == 37
    by = {x["key"]: x for x in m["stats"]["all"]}
    assert by["passes_accurate"] == {"key": "passes_accurate", "group": "passes", "home": 273, "away": 156,
                                     "home_pct": 90, "away_pct": 83}
    assert (by["ground_duels_won"]["home"], by["ground_duels_won"]["home_pct"]) == (17, 52)
    assert (by["aerials_won"]["away"], by["aerials_won"]["away_pct"]) == (4, 44)
    assert (by["dribbles"]["home_pct"], by["dribbles"]["away_pct"]) == (60, 63)
    assert by["xg_open_play"]["home"] == 1.46 and by["xg_set_play"]["home"] == 0.03 and by["xg_non_penalty"]["away"] == 0.21
    assert by["big_chances_missed"]["away"] == 1 and by["passes_own_half"]["home"] == 155
    assert by["passes_opp_half"]["away"] == 93 and by["throws"]["home"] == 8 and by["blocks"]["away"] == 2
    assert by["duels_won"]["home"] == 22 and "home_pct" not in by["duels_won"]
    # по таймам — то же: в лайве на 46′ есть только первый тайм
    assert len(m["stats"]["first_half"]) == 37 and m["stats"]["second_half"] == []


def test_attacking_zones_by_period():
    m = fotmob.normalize_match(_live_raw())
    assert m["zones"]["all"] == {"home": {"left": 59, "center": 21, "right": 20},
                                 "away": {"left": 42, "center": 24, "right": 34}}
    assert set(m["zones"]) == {"all", "first_half"}
    full = fotmob.normalize_match(load("fotmob_match_6106274.json"))
    assert set(full["zones"]) == {"all", "first_half", "second_half"}
    assert full["zones"]["second_half"]["away"] == {"left": 46, "center": 28, "right": 26}


def test_sofascore_stats_duels_with_percentages():
    m = sofascore.normalize_match(sofa_bundle(), {})
    by = {x["key"]: x for x in m["stats"]["all"]}
    assert (by["ground_duels_won"]["home"], by["ground_duels_won"]["home_pct"]) == (26, 38)
    assert by["long_balls_accurate"]["home_pct"] == 62 and by["big_chances_missed"]["away"] == 2
    assert "home_pct" not in by["possession"]          # «54%» без скобок — это не точность


# ================= смена источника не теряет блоки =================

def test_static_blocks_survive_fallback_source():
    now = time.time()
    fm = fotmob.normalize_match(load("fotmob_match_6106274.json"))
    prev = {"source": "fotmob", "fetched_at": now - 600, "data": fm}
    es = espn.normalize_match(load("espn_summary_401915414.json"), {"match_id": 6106274})
    got = borrow_static_blocks(prev, es, now)
    assert set(got) == {"venue_details", "referee_stats", "weather"}
    assert es["venue"]["capacity"] == 70634 and es["referee_info"]["id"] == fm["referee_info"]["id"]
    assert es["weather"] == fm["weather"] and es["borrowed"]["weather"]["source"] == "fotmob"
    assert {"venue_details", "referee_stats", "weather"} <= set(es["available"])
    # погода старше 6 ч не тянется
    es2 = espn.normalize_match(load("espn_summary_401915414.json"), {"match_id": 6106274})
    assert "weather" not in borrow_static_blocks({**prev, "fetched_at": now - 7 * 3600}, es2, now)


def test_zones_borrowed_in_live():
    from app.collector import borrow_live_blocks
    now = time.time()
    fm = fotmob.normalize_match(_live_raw())
    prev = {"source": "fotmob", "fetched_at": now - 30, "data": fm}
    ss = sofascore.normalize_match(sofa_bundle(), {})
    ss["status"] = status("live", 47)
    assert "zones" in borrow_live_blocks(prev, ss, now) and ss["zones"] == fm["zones"]
