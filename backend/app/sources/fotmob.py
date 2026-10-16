"""FotMob — основной источник и канонические id.

Один запрос teams?id=8633 даёт календарь, таблицы (Ла Лига, ЛЧ), состав, травмы,
лидеров и трансферы. matchDetails — всё по матчу одним ответом.
"""
import re

from .. import config
from ..model import (empty_match, event, finish_match, img_flag, img_league, img_player, img_team,
                     iso_utc, lineup_player, person, result_for, stat_list, status)
from .base import HttpxSource

BASE = "https://www.fotmob.com/api/data"


class FotMob(HttpxSource):
    name = "fotmob"

    async def team(self, team_id: int = config.TEAM_ID) -> dict:
        return await self.get(f"{BASE}/teams", {"id": team_id}, kind="team")

    async def match(self, match_id) -> dict:
        return await self.get(f"{BASE}/matchDetails", {"matchId": match_id}, kind="match")

    async def matches_on(self, yyyymmdd: str) -> dict:
        return await self.get(f"{BASE}/matches", {"date": yyyymmdd}, kind="matches_by_date")


# ---------- статусы ----------

_MIN_RE = re.compile(r"(\d+)\s*(?:\+\s*(\d+))?")


def _minute(live_time: dict | None) -> tuple[int | None, int | None]:
    m = _MIN_RE.search(str((live_time or {}).get("short") or ""))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None


def _status(st: dict) -> dict:
    reason = (st.get("reason") or {}).get("short") or ""
    if st.get("cancelled"):
        rl = ((st.get("reason") or {}).get("longKey") or "").lower()
        return status("postponed" if "postpone" in rl or reason.lower().startswith("pp") else "cancelled",
                      label=reason or None)
    if st.get("finished") or st.get("awarded"):
        if (st.get("reason") or {}).get("longKey") == "abandoned":
            return status("abandoned", label=reason)
        return status("finished", label=reason or "FT")
    if st.get("started"):
        if reason.upper() == "HT":
            return status("halftime", 45, label="HT")
        mi, add = _minute(st.get("liveTime"))
        lt = st.get("liveTime") or {}
        return status("live", mi, add, label=re.sub(r"[^\d+:’']", "", lt.get("long") or lt.get("short") or ""))
    return status("scheduled")


# ---------- матч ----------

_STATS = {
    "BallPossesion": "possession", "expected_goals": "xg", "total_shots": "shots_total",
    "ShotsOnTarget": "shots_on_target", "big_chance": "big_chances", "corners": "corners",
    "ShotsOffTarget": "shots_off_target", "blocked_shots": "shots_blocked",
    "shots_woodwork": "shots_woodwork", "shots_inside_box": "shots_inside_box",
    "shots_outside_box": "shots_outside_box", "expected_goals_on_target": "xg_on_target",
    "passes": "passes_total", "accurate_passes": "passes_accurate",
    "long_balls_accurate": "long_balls_accurate", "accurate_crosses": "crosses_accurate",
    "touches_opp_box": "touches_opp_box", "matchstats.headers.tackles": "tackles",
    "interceptions": "interceptions", "clearances": "clearances", "keeper_saves": "saves",
    "fouls": "fouls", "Offsides": "offsides", "yellow_cards": "yellow_cards", "red_cards": "red_cards",
}
_PERIODS = {"All": "all", "FirstHalf": "first_half", "SecondHalf": "second_half"}
_SHOT = {"Goal": "goal", "AttemptSaved": "saved", "Miss": "miss", "Post": "post"}
_POS = {0: "GK", 1: "DF", 2: "MF", 3: "FW"}
_CARD = {"yellow": "yellow", "red": "red", "yellowred": "second_yellow"}


def _stats(periods: dict) -> dict | None:
    out = {}
    for src_key, our in _PERIODS.items():
        pairs = {}
        for g in (periods.get(src_key) or {}).get("stats") or []:
            for s in g.get("stats") or []:
                k = _STATS.get(s.get("key"))
                vals = s.get("stats") or []
                if k and s.get("type") != "title" and len(vals) == 2 and k not in pairs:
                    pairs[k] = (vals[0], vals[1])
        out[our] = stat_list(pairs)
    return out if out.get("all") else None


def _events(raw_events: list, home_id) -> tuple[list, list | None]:
    out, ht = [], None
    for e in raw_events:
        ty = e.get("type")
        side = "home" if e.get("isHome") else "away"
        mi, add = e.get("time"), e.get("overloadTime") or None
        p = e.get("player") or {}
        if ty == "Goal":
            desc = f"{e.get('goalDescriptionKey') or ''} {e.get('suffixKey') or ''}".lower()
            out.append(event(
                "goal", mi, add, side,
                player=person(name=p.get("name"), fotmob_id=p.get("id")),
                assist=person(name=e.get("assistInput"), fotmob_id=e.get("assistPlayerId"))
                if e.get("assistInput") else None,
                own_goal=bool(e.get("ownGoal")),
                penalty="penalty" in desc,
                shootout=bool(e.get("isPenaltyShootoutEvent")),
                score=list(e.get("newScore") or [e.get("homeScore"), e.get("awayScore")]),
            ))
        elif ty == "Card":
            card = _CARD.get(re.sub(r"[^a-z]", "", (e.get("card") or "").lower()), "yellow")
            out.append(event("card", mi, add, side, card=card,
                             player=person(name=p.get("name"), fotmob_id=p.get("id")),
                             reason=(e.get("cardReason") or {}).get("defaultText")))
        elif ty == "Substitution":
            sw = (e.get("swap") or []) + [{}, {}]
            out.append(event("sub", mi, add, side,
                             player_in=person(name=sw[0].get("name"), fotmob_id=sw[0].get("id")),
                             player_out=person(name=sw[1].get("name"), fotmob_id=sw[1].get("id")),
                             injury=bool(e.get("injuredPlayerOut"))))
        elif ty == "Half":
            label = e.get("halfStrShort")
            out.append(event("period", mi, None, None, label=label,
                             score=[e.get("homeScore"), e.get("awayScore")]))
            if label == "HT":
                ht = [e.get("homeScore"), e.get("awayScore")]
        elif ty == "AddedTime":
            out.append(event("added_time", mi, None, None, minutes=e.get("minutesAddedInput")))
        elif ty == "VAR":
            var = e.get("VAR") or {}
            dec = var.get("decision")
            out.append(event("var", mi, add, side,
                             player=person(name=p.get("name"), fotmob_id=p.get("id")),
                             decision=(dec.get("value") if isinstance(dec, dict) else dec) or None,
                             text=str(var.get("decision") or "") or None))
    return out, ht


def _lineup_side(s: dict) -> dict:
    def pl(p, starter):
        perf = p.get("performance") or {}
        lay = p.get("verticalLayout") or {}
        sub_in = next((x.get("time") for x in perf.get("substitutionEvents") or [] if x.get("type") == "subIn"), None)
        sub_out = next((x.get("time") for x in perf.get("substitutionEvents") or [] if x.get("type") == "subOut"), None)
        return lineup_player(
            p.get("name"), p.get("shirtNumber"), fotmob_id=p.get("id"),
            position="GK" if p.get("positionId") == 11 else _POS.get(p.get("usualPlayingPositionId")),
            rating=perf.get("rating"),
            x=round(lay["x"], 3) if starter and "x" in lay else None,
            y=round(lay["y"], 3) if starter and "y" in lay else None,
            captain=p.get("isCaptain"), sub_in=sub_in, sub_out=sub_out, source_id=p.get("id"))

    coach = s.get("coach") or {}
    return {
        "team_id": s.get("id"), "formation": s.get("formation"),
        "rating": s.get("rating"),
        "coach": {"id": coach.get("id"), "name": coach.get("name")} if coach.get("name") else None,
        "starters": [pl(p, True) for p in s.get("starters") or []],
        "subs": [pl(p, False) for p in s.get("subs") or []],
        "unavailable": [{
            "id": p.get("id"), "name": p.get("name"), "photo": img_player(p.get("id")),
            "type": (p.get("unavailability") or {}).get("type"),
            "expected_return": (p.get("unavailability") or {}).get("expectedReturn"),
        } for p in s.get("unavailable") or []],
    }


def normalize_match(raw: dict) -> dict:
    m = empty_match()
    g = raw.get("general") or {}
    h = raw.get("header") or {}
    c = raw.get("content") or {}
    mf = c.get("matchFacts") or {}
    info = mf.get("infoBox") or {}
    teams = (h.get("teams") or []) + [{}, {}]
    home_id = teams[0].get("id")

    mid = int(g.get("matchId") or mf.get("matchId") or 0) or None
    m["id"] = mid
    m["ids"]["fotmob"] = mid
    m["kickoff"] = iso_utc(g.get("matchTimeUTCDate") or (h.get("status") or {}).get("utcTime"))
    m["status"] = _status(h.get("status") or {})
    lid = g.get("parentLeagueId") or g.get("leagueId")
    m["tournament"] = {"id": lid, "name": g.get("leagueName"), "round": g.get("leagueRoundName") or None,
                       "logo": img_league(lid)}
    stadium = info.get("Stadium") or {}
    if stadium.get("name"):
        m["venue"] = {"name": stadium.get("name"), "city": stadium.get("city")}
    m["referee"] = (info.get("Referee") or {}).get("text") or None
    m["attendance"] = info.get("Attendance")
    for i, key in enumerate(("home", "away")):
        t = teams[i]
        m[key].update(id=t.get("id"), name=t.get("name"), short=t.get("name"),
                      score=t.get("score") if m["status"]["state"] != "scheduled" else None,
                      logo=img_team(t.get("id")))

    m["events"], ht = _events((mf.get("events") or {}).get("events") or [], home_id)
    if ht:
        m["home"]["ht_score"], m["away"]["ht_score"] = ht

    lu = c.get("lineup") or {}
    if (lu.get("homeTeam") or {}).get("starters"):
        m["lineups"] = {
            "confirmed": (lu.get("lineupType") or "").lower() != "predicted",
            "home": _lineup_side(lu["homeTeam"]),
            "away": _lineup_side(lu.get("awayTeam") or {}),
        }

    m["stats"] = _stats((c.get("stats") or {}).get("Periods") or {})

    for s in (c.get("shotmap") or {}).get("shots") or []:
        outcome = "blocked" if s.get("isBlocked") else _SHOT.get(s.get("eventType"), "miss")
        m["shots"].append({
            "x": round((s.get("x") or 0) / 105 * 100, 1), "y": round((s.get("y") or 0) / 68 * 100, 1),
            "minute": s.get("min"), "added": s.get("minAdded"),
            "side": "home" if s.get("teamId") == home_id else "away",
            "player": person(name=s.get("playerName"), fotmob_id=s.get("playerId")),
            "outcome": outcome, "own_goal": bool(s.get("isOwnGoal")),
            "xg": round(s["expectedGoals"], 3) if s.get("expectedGoals") is not None else None,
            "xgot": round(s["expectedGoalsOnTarget"], 3) if s.get("expectedGoalsOnTarget") else None,
            "situation": s.get("situation"), "body": s.get("shotType"), "period": s.get("period"),
        })

    # в лайве FotMob заранее кладёт будущие минуты со value=null — отбрасываем
    m["momentum"] = [{"minute": p.get("minute"), "value": p.get("value")}
                     for p in ((c.get("momentum") or {}).get("main") or {}).get("data") or []
                     if p.get("value") is not None]

    potm = mf.get("playerOfTheMatch") or {}
    if potm.get("id"):
        m["potm"] = {**person(name=(potm.get("name") or {}).get("fullName"), fotmob_id=potm.get("id")),
                     "side": "home" if potm.get("teamId") == home_id else "away",
                     "rating": float((potm.get("rating") or {}).get("num") or 0) or None}

    hl = mf.get("highlights") or {}
    if hl.get("url"):
        m["highlights"] = {"url": hl.get("url"), "image": hl.get("image"), "source": hl.get("source")}

    h2h = c.get("h2h") or {}
    if h2h.get("matches") or h2h.get("summary"):
        summ = (h2h.get("summary") or []) + [None, None, None]
        m["h2h"] = {
            "summary": {"home_wins": summ[0], "draws": summ[1], "away_wins": summ[2]},
            "matches": [{
                "kickoff": iso_utc((x.get("time") or {}).get("utcTime")),
                "tournament": (x.get("league") or {}).get("name"),
                "home": {"id": _int((x.get("home") or {}).get("id")), "name": (x.get("home") or {}).get("name")},
                "away": {"id": _int((x.get("away") or {}).get("id")), "name": (x.get("away") or {}).get("name")},
                "score": (x.get("status") or {}).get("scoreStr"),
                "finished": bool((x.get("status") or {}).get("finished")),
            } for x in h2h.get("matches") or []][:10],
        }

    tf = mf.get("teamForm") or []
    if len(tf) == 2:
        m["form"] = {k: [{"result": f.get("resultString"), "score": f.get("score"),
                          "kickoff": iso_utc((f.get("date") or {}).get("utcTime"))} for f in side]
                     for k, side in zip(("home", "away"), tf)}
    return finish_match(m, "fotmob")


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------- календарь ----------

def _fixture(f: dict) -> dict:
    st = f.get("status") or {}
    lid = (f.get("tournament") or {}).get("leagueId")
    s = _status(st)
    home, away = f.get("home") or {}, f.get("away") or {}
    started = s["state"] not in ("scheduled", "postponed", "cancelled")
    hs, as_ = (home.get("score"), away.get("score")) if started else (None, None)
    return {
        "id": f.get("id"),
        "ids": {"fotmob": f.get("id"), "sofascore": None, "espn": None, "livescore": None},
        "kickoff": iso_utc(st.get("utcTime")),
        "tournament": {"id": lid, "name": (f.get("tournament") or {}).get("name"),
                       "round": (f.get("tournament") or {}).get("stage") or None, "logo": img_league(lid)},
        "home": {"id": home.get("id"), "name": home.get("name"), "score": hs, "logo": img_team(home.get("id"))},
        "away": {"id": away.get("id"), "name": away.get("name"), "score": as_, "logo": img_team(away.get("id"))},
        "status": s,
        "is_home": home.get("id") == config.TEAM_ID,
        "result": result_for(config.TEAM_ID, home.get("id"), hs, as_) if s["finished"] else None,
    }


def normalize_fixtures(raw_team: dict) -> list:
    fx = ((raw_team.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or []
    out = [_fixture(f) for f in fx if (f.get("tournament") or {}).get("leagueId") in config.LEAGUES]
    out.sort(key=lambda x: x["kickoff"] or "")
    return out


# ---------- таблицы ----------

def _table(block: dict) -> dict | None:
    d = block.get("data") or {}
    lid = d.get("leagueId")
    tbl = d.get("table") or {}
    rows = tbl.get("all") if isinstance(tbl, dict) else None
    if not rows and d.get("tables"):  # групповой формат
        rows = ((d["tables"][0].get("table") or {}).get("all")) or []
    if not rows:
        return None
    zones = {}
    for lg in d.get("legend") or []:
        for i in lg.get("indices") or []:
            zones[i] = {"label": lg.get("title"), "color": lg.get("color")}
    out_rows = []
    for i, r in enumerate(rows):
        gf, _, ga = (r.get("scoresStr") or "-").partition("-")
        out_rows.append({
            "pos": r.get("idx") or i + 1,
            "team": {"id": r.get("id"), "name": r.get("name"), "short": r.get("shortName") or r.get("name"),
                     "logo": img_team(r.get("id"))},
            "played": r.get("played"), "w": r.get("wins"), "d": r.get("draws"), "l": r.get("losses"),
            "gf": _int(gf), "ga": _int(ga), "gd": r.get("goalConDiff"), "pts": r.get("pts"),
            "zone": zones.get(i),
            "is_us": r.get("id") == config.TEAM_ID,
        })
    return {"league": {"id": lid, "name": d.get("leagueName"), "logo": img_league(lid)}, "rows": out_rows}


def normalize_tables(raw_team: dict) -> list:
    out = [t for t in (_table(b) for b in raw_team.get("table") or []) if t]
    return [t for t in out if t["league"]["id"] in config.TABLE_LEAGUES]


# ---------- команда ----------

_LINES = {"keepers": "goalkeepers", "defenders": "defenders", "midfielders": "midfielders",
          "attackers": "attackers"}


def _transfer(t: dict) -> dict:
    fee = t.get("fee") or {}
    return {
        "player": {"id": t.get("playerId"), "name": t.get("name"), "photo": img_player(t.get("playerId"))},
        "position": (t.get("position") or {}).get("label") if isinstance(t.get("position"), dict) else t.get("position"),
        "date": iso_utc(t.get("transferDate")),
        "from": {"id": t.get("fromClubId"), "name": t.get("fromClub"), "logo": img_team(t.get("fromClubId"))},
        "to": {"id": t.get("toClubId"), "name": t.get("toClub"), "logo": img_team(t.get("toClubId"))},
        "fee_text": fee.get("feeText") if isinstance(fee, dict) else None,
        "fee_eur": fee.get("value") if isinstance(fee, dict) else None,
        "loan": bool(t.get("onLoan")),
    }


def normalize_team(raw: dict) -> dict:
    ov = raw.get("overview") or {}
    groups = (raw.get("squad") or {}).get("squad") or []
    squad = {v: [] for v in _LINES.values()}
    coach = None
    injuries = {}
    for g in groups:
        if g.get("title") == "coach":
            c = (g.get("members") or [None])[0]
            if c:
                coach = {"id": c.get("id"), "name": c.get("name"), "photo": img_player(c.get("id")),
                         "country": {"code": c.get("ccode"), "name": c.get("cname"), "flag": img_flag(c.get("ccode"))}}
            continue
        line = _LINES.get(g.get("title"))
        if not line:
            continue
        for p in g.get("members") or []:
            inj = p.get("injury") or None
            squad[line].append({
                "id": p.get("id"), "name": p.get("name"), "number": p.get("shirtNumber"),
                "position": p.get("positionIdsDesc"), "age": p.get("age"), "birth": p.get("dateOfBirth"),
                "height": p.get("height"),
                "country": {"code": p.get("ccode"), "name": p.get("cname"), "flag": img_flag(p.get("ccode"))},
                "photo": img_player(p.get("id")),
                "rating": p.get("rating"), "goals": p.get("goals"), "assists": p.get("assists"),
                "yellow": p.get("ycards"), "red": p.get("rcards"), "value_eur": p.get("transferValue"),
                "injured": bool(inj),
            })
            if inj:
                injuries[p.get("id")] = {"id": p.get("id"), "name": p.get("name"), "photo": img_player(p.get("id")),
                                         "type": "injury", "expected_return": inj.get("expectedReturn")}
    for p in (ov.get("lastLineupStats") or {}).get("unavailable") or []:
        un = p.get("unavailability") or {}
        injuries.setdefault(p.get("id"), {"id": p.get("id"), "name": p.get("name"), "photo": img_player(p.get("id")),
                                          "type": un.get("type"), "expected_return": un.get("expectedReturn")})

    def tops(key):
        return [{"id": p.get("id"), "name": p.get("name"), "value": p.get("value"), "photo": img_player(p.get("id"))}
                for p in ((ov.get("topPlayers") or {}).get(key) or {}).get("players") or []]

    tr = ((raw.get("transfers") or {}).get("data")) or {}
    venue = (ov.get("venue") or {}).get("widget") or {}
    return {
        "team": {"id": config.TEAM_ID, "name": (raw.get("details") or {}).get("name") or "Real Madrid",
                 "logo": img_team(config.TEAM_ID)},
        "venue": {"name": venue.get("name"), "city": venue.get("city")} if venue.get("name") else None,
        "coach": coach,
        "squad": squad,
        "injuries": list(injuries.values()),
        "leaders": {"goals": tops("byGoals"), "assists": tops("byAssists"), "rating": tops("byRating")},
        "transfers": {"in": [_transfer(t) for t in tr.get("Players in") or []],
                      "out": [_transfer(t) for t in tr.get("Players out") or []]},
        "source": "fotmob",
        "available": ["squad", "player_photos", "injuries", "leaders", "transfers", "coach"],
    }
