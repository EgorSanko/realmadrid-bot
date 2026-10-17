"""Нормализаторы всех 4 источников на реальных сохранённых ответах (матч Рома 3:4 Реал, ЛЧ, 14.10.2026).

FotMob 6106274, SofaScore 16938872, ESPN 401915414, LiveScore 1882774.
"""
import pytest

from app import config
from app.model import AVAILABLE_KEYS, iso2, same_person
from app.sources import espn, fotmob, livescore, sofascore

from .conftest import load, ls_bundle, sofa_bundle


@pytest.fixture(scope="module")
def matches():
    return {
        "fotmob": fotmob.normalize_match(load("fotmob_match_6106274.json")),
        "sofascore": sofascore.normalize_match(sofa_bundle(), {"match_id": 6106274}),
        "espn": espn.normalize_match(load("espn_summary_401915414.json"), {"match_id": 6106274}),
        "livescore": livescore.normalize_match(ls_bundle()),
    }


def goals(m):
    return [e for e in m["events"] if e["type"] == "goal"]


def test_same_score_and_status(matches):
    for name, m in matches.items():
        assert (m["home"]["score"], m["away"]["score"]) == (3, 4), name
        assert (m["home"]["ht_score"], m["away"]["ht_score"]) == (1, 1), name
        assert m["status"]["state"] == "finished", name
        assert m["kickoff"] == "2026-10-14T19:00:00Z", name
        assert m["tournament"]["id"] == 42, name
        assert m["source"] == name
        assert m["id"] == 6106274, name  # канонический id FotMob (LiveScore сам знает его из Pids)


def test_same_goals_scorers_and_minutes(matches):
    ref = goals(matches["fotmob"])
    assert len(ref) == 7
    assert [g["side"] for g in ref] == ["home", "away", "home", "home", "away", "away", "away"]
    for name, m in matches.items():
        g = goals(m)
        assert len(g) == 7, name
        assert [x["side"] for x in g] == [x["side"] for x in ref], name
        for a, b in zip(g, ref):
            assert same_person(a["player"]["name"], b["player"]["name"]), (name, a["player"], b["player"])
            # минуты совпадают; единственное расхождение источников — гол Эспи: 82' (FotMob, LiveScore) / 83' (SofaScore, ESPN)
            assert abs(a["minute"] - b["minute"]) <= 1, (name, a["minute"], b["minute"])
        assert [x["score"] for x in g] == [[1, 0], [1, 1], [2, 1], [3, 1], [3, 2], [3, 3], [3, 4]], name


def test_minutes_exact_except_known(matches):
    ref = [g["minute"] for g in goals(matches["fotmob"])]
    assert ref == [20, 25, 51, 57, 82, 85, 90]
    assert [g["minute"] for g in goals(matches["livescore"])] == ref
    for name in ("sofascore", "espn"):
        assert [g["minute"] for g in goals(matches[name])] == [20, 25, 51, 57, 83, 85, 90]


def test_cards_and_subs(matches):
    for name, m in matches.items():
        cards = [e for e in m["events"] if e["type"] == "card"]
        subs = [e for e in m["events"] if e["type"] == "sub"]
        assert len(cards) == 4 and all(c["card"] == "yellow" for c in cards), name
        assert len(subs) == 10, name
        assert all(s["player_in"] and s["player_out"] for s in subs), name


def test_same_structure(matches):
    keys = {name: set(m) for name, m in matches.items()}
    assert len({frozenset(k) for k in keys.values()}) == 1, keys
    gkeys = {name: set(goals(m)[0]) for name, m in matches.items()}
    assert len({frozenset(k) for k in gkeys.values()}) == 1, gkeys
    for name, m in matches.items():
        assert set(m["available"]) <= set(AVAILABLE_KEYS)
        lu = m["lineups"]
        assert lu and len(lu["home"]["starters"]) == 11 and len(lu["away"]["starters"]) == 11, name
        pkeys = set(lu["home"]["starters"][0])
        assert pkeys == set(matches["fotmob"]["lineups"]["home"]["starters"][0]), name
        if m["shots"]:
            assert set(m["shots"][0]) == set(matches["fotmob"]["shots"][0]), name
        for it in m["stats"]["all"]:
            assert set(it) == {"key", "group", "home", "away"}


def test_available_is_honest(matches):
    a = {n: set(m["available"]) for n, m in matches.items()}
    full = {"events", "assists", "lineups", "lineup_positions", "ratings", "stats", "stats_periods", "xg",
            "shotmap", "shot_xg", "momentum", "potm", "highlights", "h2h", "form", "venue", "referee", "player_photos"}
    assert a["fotmob"] == full
    assert {"ratings", "shotmap", "momentum", "potm", "xg", "stats_periods"} <= a["sofascore"]
    for k in ("ratings", "xg", "shotmap", "momentum", "potm", "lineup_positions"):
        assert k not in a["espn"], k
    assert "ratings" not in a["livescore"] and "shotmap" in a["livescore"] and "shot_xg" not in a["livescore"]
    # пустые блоки действительно пустые
    e = matches["espn"]
    assert e["shots"] == [] and e["momentum"] == [] and e["potm"] is None
    assert all(p["rating"] is None for p in e["lineups"]["home"]["starters"])


def test_stats_agree(matches):
    def stat(m, k):
        return next(((x["home"], x["away"]) for x in m["stats"]["all"] if x["key"] == k), None)
    for name, m in matches.items():
        assert stat(m, "shots_total") == (14, 16), name
        assert stat(m, "shots_on_target") == (7, 8), name
        assert stat(m, "possession") == (54, 46), name
        assert stat(m, "corners") == (5, 9), name
    assert stat(matches["fotmob"], "xg") == stat(matches["sofascore"], "xg") == (1.41, 1.43)


def test_shotmap_coordinates_agree(matches):
    """Голы на карте ударов в одной системе координат (x 0..100 к атакуемым воротам, y 0..100)."""
    ref = [s for s in matches["fotmob"]["shots"] if s["outcome"] == "goal"]
    for name in ("sofascore", "livescore"):
        other = [s for s in matches[name]["shots"] if s["outcome"] == "goal"]
        assert len(other) == 7, name
        for a in ref:
            assert any(abs(a["x"] - b["x"]) < 3 and abs(a["y"] - b["y"]) < 4 and a["side"] == b["side"]
                       for b in other), (name, a)


def test_ratings_and_potm(matches):
    fm, ss = matches["fotmob"], matches["sofascore"]
    assert fm["potm"]["name"] == "Donyell Malen" and fm["potm"]["rating"] == 8.7
    assert ss["potm"]["name"] == "Donyell Malen" and ss["potm"]["side"] == "home"
    assert fm["lineups"]["home"]["starters"][0]["photo"] == "/img/player/553849.png"
    assert fm["home"]["logo"] == "/img/team/8686.png" and fm["tournament"]["logo"] == "/img/league/42.png"
    assert fm["highlights"]["url"].startswith("https://www.youtube.com/")


def test_lineup_positions_match_fotmob(matches):
    """Координаты по схеме (SofaScore, LiveScore) совпадают с verticalLayout FotMob по линиям защиты."""
    ref = {p["number"]: (p["x"], p["y"]) for p in matches["fotmob"]["lineups"]["away"]["starters"]}
    for name in ("sofascore", "livescore"):
        for p in matches[name]["lineups"]["away"]["starters"][:5]:  # вратарь и четвёрка защитников
            assert abs(p["x"] - ref[p["number"]][0]) < 0.02 and abs(p["y"] - ref[p["number"]][1]) < 0.02, (name, p)


def test_player_photos_via_ctx():
    """Резервный источник получает фото, если сборщик знает id FotMob (по номеру в составе)."""
    fm = fotmob.normalize_match(load("fotmob_match_6106274.json"))
    from app.collector import _ctx_from_match
    ctx = {"match_id": 6106274, **_ctx_from_match(fm), "teams": {"2702": 8686, "2829": 8633}}
    ss = sofascore.normalize_match(sofa_bundle(), ctx)
    assert "player_photos" in ss["available"]
    mb = next(g for g in ss["events"] if g["type"] == "goal" and "Mbapp" in g["player"]["name"])
    assert mb["player"]["photo"] == "/img/player/701154.png"
    assert ss["home"]["logo"] == "/img/team/8686.png"


# ---------- календарь / таблицы / команда ----------

def test_fotmob_team_payload():
    raw = load("fotmob_team_8633.json")
    fx = fotmob.normalize_fixtures(raw)
    assert {f["tournament"]["id"] for f in fx} <= set(config.LEAGUES)
    assert len(fx) == 47  # 38 Ла Лига + 8 ЛЧ + 1 Суперкубок (товарищеские отброшены)
    roma = next(f for f in fx if f["id"] == 6106274)
    assert (roma["home"]["score"], roma["away"]["score"], roma["result"]) == (3, 4, "W")
    nxt = next(f for f in fx if not f["status"]["finished"])
    assert nxt["id"] == 5868098 and nxt["kickoff"] == "2026-10-18T19:00:00Z" and nxt["away"]["name"] == "Sevilla"
    tables = fotmob.normalize_tables(raw)
    assert [t["league"]["id"] for t in tables] == [87, 42]
    assert len(tables[0]["rows"]) == 20 and len(tables[1]["rows"]) == 36
    assert sum(r["is_us"] for r in tables[0]["rows"]) == 1
    team = fotmob.normalize_team(raw)
    assert sum(len(v) for v in team["squad"].values()) == 26
    assert team["coach"]["name"] and team["leaders"]["goals"] and team["transfers"]["in"]


def test_sofa_and_espn_fixtures_and_tables():
    evs = load("sofa_team_last.json")["events"] + load("sofa_team_next.json")["events"]
    sf = sofascore.normalize_fixtures(evs, {"matches": {"16938872": "6106274"}})
    roma = next(f for f in sf if f["ids"]["sofascore"] == 16938872)
    assert roma["id"] == 6106274 and roma["result"] == "W" and (roma["home"]["score"], roma["away"]["score"]) == (3, 4)
    assert all(isinstance(f["id"], int) or f["id"].startswith("sofascore:") for f in sf)
    sched = {s: [load(f"espn_sched_{s}_past.json"), load(f"espn_sched_{s}_next.json")]
             for s in ("esp.1", "uefa.champions", "esp.copa_del_rey", "esp.super_cup")}
    ef = espn.normalize_fixtures(sched)
    r2 = next(f for f in ef if f["ids"]["espn"] == "401915414")
    assert r2["result"] == "W" and r2["kickoff"] == "2026-10-14T19:00:00Z"
    t = espn.normalize_table(load("espn_standings_esp.1.json"), 87)
    assert len(t["rows"]) == 20 and sum(r["is_us"] for r in t["rows"]) == 1
    fm_rm = next(r for r in fotmob.normalize_tables(load("fotmob_team_8633.json"))[0]["rows"] if r["is_us"])
    es_rm = next(r for r in t["rows"] if r["is_us"])
    assert (fm_rm["pos"], fm_rm["pts"], fm_rm["played"]) == (es_rm["pos"], es_rm["pts"], es_rm["played"])
    cl = espn.normalize_table(load("espn_standings_uefa.champions.json"), 42)
    assert len(cl["rows"]) == 36


def test_flags_cover_all_codes():
    raw = load("fotmob_team_8633.json")
    codes = {p.get("ccode") for g in raw["squad"]["squad"] for p in g["members"]}
    lu = load("fotmob_match_6106274.json")["content"]["lineup"]
    codes |= {p.get("countryCode") for s in ("homeTeam", "awayTeam") for p in lu[s]["starters"] + lu[s]["subs"]}
    codes.discard(None)
    missing = {c for c in codes if not iso2(c)}
    assert not missing, missing
    assert iso2("POR") == "pt" and iso2("ENG") == "gb-eng" and iso2("SCO") == "gb-sct" and iso2("WAL") == "gb-wls"


def test_images_for_venue_referee_and_form(matches):
    """Картинки, которые источник уже отдаёт: флаг страны стадиона и судьи, id соперников в форме."""
    fm = matches["fotmob"]
    assert fm["venue"] == {"name": "Stadio Olimpico", "city": "Roma", "country": "Italy", "flag": "/img/flag/it.svg"}
    assert fm["referee"] == "François Letexier"
    assert fm["referee_country"] == {"code": "FRA", "name": "France", "flag": "/img/flag/fr.svg"}
    # форма: соперник — та команда, что не isOurTeam; id FotMob → /img/team/{id}.png
    first = fm["form"]["home"][0]
    assert first["opponent"] == {"id": 8524, "name": "Atalanta"}
    assert all(f["opponent"] and f["opponent"]["id"] for side in ("home", "away") for f in fm["form"][side])
    assert all(f["opponent"]["id"] != 8686 for f in fm["form"]["home"])  # не сама Рома
    assert all(f["opponent"]["id"] != 8633 for f in fm["form"]["away"])  # не сам Реал

    sf = matches["sofascore"]
    assert sf["venue"]["flag"] == "/img/flag/it.svg"
    assert sf["referee_country"]["flag"] == "/img/flag/fr.svg"
    es = matches["espn"]
    assert es["venue"]["country"] == "Italy" and es["venue"]["flag"] == "/img/flag/it.svg"
    assert all(f["opponent"] is None for f in es["form"]["home"])  # id ESPN — не FotMob, эмблемы не будет
    ls = matches["livescore"]
    assert ls["venue"] is None or ls["venue"]["flag"] is None
    assert ls["referee_country"] is None


def test_country_by_name_unknown_gives_no_flag():
    from app.model import country_ref, venue
    assert venue("Somewhere", "X", "Atlantis") == {"name": "Somewhere", "city": "X", "country": "Atlantis", "flag": None}
    assert venue(None, "X", "Spain") is None
    assert country_ref(None, None) is None
    assert country_ref("ESP", None)["flag"] == "/img/flag/es.svg"
    assert country_ref(None, "England")["flag"] == "/img/flag/gb-eng.svg"
