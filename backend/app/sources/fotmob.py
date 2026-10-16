"""FotMob — основной источник: команда, календарь, таблицы, матч в лайве.

Сырые ответы приводим к своим компактным формам здесь же, чтобы фронт
не зависел от того, как FotMob завтра переименует поля.
"""
from ..cache import cached
from ..http import get_json

TEAM_ID = 8633  # Real Madrid
BASE = "https://www.fotmob.com/api/data"

TEAM_TTL = 600        # календарь/состав/таблица меняются редко
MATCH_TTL_LIVE = 15   # во время матча
MATCH_TTL_IDLE = 300  # до/после матча


def team_logo(team_id) -> str:
    return f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}.png"


def player_photo(player_id) -> str:
    return f"https://images.fotmob.com/image_resources/playerimages/{player_id}.png"


# ---------- сырые запросы ----------

async def raw_team() -> dict:
    return await cached("fm:team", TEAM_TTL, lambda: get_json(f"{BASE}/teams", id=TEAM_ID))


async def raw_match(match_id: int, live_hint: bool = False) -> dict:
    ttl = MATCH_TTL_LIVE if live_hint else MATCH_TTL_IDLE
    return await cached(f"fm:match:{match_id}", ttl,
                        lambda: get_json(f"{BASE}/matchDetails", matchId=match_id))


# ---------- команда ----------

def _side(t: dict) -> dict:
    return {"id": t.get("id"), "name": t.get("name"), "score": t.get("score"),
            "logo": team_logo(t.get("id"))}


def _fixture(f: dict) -> dict:
    st = f.get("status") or {}
    started, finished = bool(st.get("started")), bool(st.get("finished"))
    lt = f.get("liveTime") or st.get("liveTime") or {}
    return {
        "id": f.get("id"),
        "utc": st.get("utcTime"),
        "date_tbd": bool(st.get("matchDateTbd")),
        "home": _side(f.get("home") or {}),
        "away": _side(f.get("away") or {}),
        "is_home": (f.get("home") or {}).get("id") == TEAM_ID,
        "tournament": (f.get("tournament") or {}).get("name"),
        "league_id": (f.get("tournament") or {}).get("leagueId"),
        "stage": (f.get("tournament") or {}).get("stage") or None,
        "state": "finished" if finished else "live" if started else
                 "cancelled" if st.get("cancelled") else "scheduled",
        "minute": lt.get("short") if started and not finished else None,
        "score": st.get("scoreStr"),
        # 1 победа, 0 ничья, -1 поражение — с точки зрения Реала
        "result": f.get("result"),
    }


def _table(block: dict) -> dict:
    data = block.get("data") or {}
    tbl = data.get("table") or {}
    rows = tbl.get("all") or []
    # у ЛЧ-формата таблица может лежать в composite/tables
    if not rows and data.get("tables"):
        rows = (data["tables"][0].get("table") or {}).get("all") or []
    return {
        "league_id": data.get("leagueId"),
        "league": data.get("leagueName"),
        "legend": [{"title": l.get("title"), "color": l.get("color")} for l in data.get("legend") or []],
        "rows": [{
            "pos": r.get("idx"), "id": r.get("id"), "name": r.get("shortName") or r.get("name"),
            "logo": team_logo(r.get("id")), "played": r.get("played"),
            "w": r.get("wins"), "d": r.get("draws"), "l": r.get("losses"),
            "goals": r.get("scoresStr"), "gd": r.get("goalConDiff"), "pts": r.get("pts"),
            "color": r.get("qualColor"), "is_us": r.get("id") == TEAM_ID,
        } for r in rows],
    }


def _squad(groups: list) -> list:
    out = []
    for g in groups:
        if g.get("title") == "coach":
            continue
        out.append({
            "key": g.get("title"),
            "players": [{
                "id": p.get("id"), "name": p.get("name"), "number": p.get("shirtNumber"),
                "age": p.get("age"), "birth": p.get("dateOfBirth"), "height": p.get("height"),
                "country": p.get("cname"), "ccode": p.get("ccode"),
                "position": p.get("positionIdsDesc"), "value": p.get("transferValue"),
                "rating": p.get("rating"), "goals": p.get("goals"), "assists": p.get("assists"),
                "yellow": p.get("ycards"), "red": p.get("rcards"),
                "injured": bool(p.get("injury")),
                "injury_return": (p.get("injury") or {}).get("expectedReturn"),
                "photo": player_photo(p.get("id")),
            } for p in g.get("members") or []],
        })
    return out


def _transfers(tr: dict) -> dict:
    def item(t):
        fee = t.get("fee") or {}
        return {
            "player_id": t.get("playerId"), "name": t.get("name"),
            "position": (t.get("position") or {}).get("label") if isinstance(t.get("position"), dict) else t.get("position"),
            "date": t.get("transferDate"),
            "from": t.get("fromClub"), "from_id": t.get("fromClubId"),
            "to": t.get("toClub"), "to_id": t.get("toClubId"),
            "fee": fee.get("value") if isinstance(fee, dict) else fee,
            "fee_text": fee.get("feeText") if isinstance(fee, dict) else None,
            "loan": bool(t.get("onLoan")),
            "photo": player_photo(t.get("playerId")),
        }
    data = (tr or {}).get("data") or {}
    return {
        "in": [item(t) for t in data.get("Players in") or []],
        "out": [item(t) for t in data.get("Players out") or []],
        "rumours": [item(t) for t in (tr or {}).get("allRumours") or []][:15],
    }


async def team() -> dict:
    t = await raw_team()
    ov = t.get("overview") or {}
    fx = (t.get("fixtures") or {}).get("allFixtures") or {}
    llu = ov.get("lastLineupStats") or {}
    coach = next((g["members"][0] for g in (t.get("squad") or {}).get("squad") or []
                  if g.get("title") == "coach" and g.get("members")), None)

    def tops(key):
        return [{"id": p.get("id"), "name": p.get("name"), "value": p.get("value"),
                 "photo": player_photo(p.get("id"))}
                for p in ((ov.get("topPlayers") or {}).get(key) or {}).get("players") or []]

    return {
        "next": _fixture(fx["nextMatch"]) if fx.get("nextMatch") else None,
        "last": _fixture(fx["lastMatch"]) if fx.get("lastMatch") else None,
        "has_live": bool(fx.get("hasOngoingMatch") or ov.get("hasOngoingMatch")),
        "fixtures": [_fixture(f) for f in fx.get("fixtures") or []],
        "form": [{"r": f.get("resultString"), "score": f.get("score"),
                  "tournament": f.get("tournamentName"),
                  "opponent": next((s.get("name") for s in (f.get("home"), f.get("away"))
                                    if s and not s.get("isOurTeam")), None)}
                 for f in ov.get("teamForm") or []],
        "tables": [_table(b) for b in t.get("table") or []],
        "squad": _squad((t.get("squad") or {}).get("squad") or []),
        "coach": {"id": coach.get("id"), "name": coach.get("name"),
                  "photo": player_photo(coach.get("id"))} if coach else None,
        "unavailable": [{
            "id": p.get("id"), "name": p.get("name"),
            "type": (p.get("unavailability") or {}).get("type"),
            "expected_return": (p.get("unavailability") or {}).get("expectedReturn"),
            "photo": player_photo(p.get("id")),
        } for p in llu.get("unavailable") or []],
        "top": {"goals": tops("byGoals"), "assists": tops("byAssists"), "rating": tops("byRating")},
        "transfers": _transfers(t.get("transfers") or ov.get("transfers") or {}),
        "venue": (ov.get("venue") or {}).get("widget", {}).get("name"),
    }


# ---------- матч ----------

def _event(e: dict) -> dict | None:
    ty = e.get("type")
    base = {
        "min": e.get("time"), "added": e.get("overloadTime") or None,
        "side": "home" if e.get("isHome") else "away",
        "score": [e.get("homeScore"), e.get("awayScore")],
    }
    p = e.get("player") or {}
    if ty == "Goal":
        return {**base, "type": "goal", "player": p.get("name"), "player_id": p.get("id"),
                "assist": e.get("assistInput") or e.get("assistStr"),
                "own_goal": bool(e.get("ownGoal")),
                "penalty": (e.get("goalDescriptionKey") or "") == "penalty" or
                           "penalty" in str(e.get("goalDescription") or "").lower(),
                "var_cancelled": bool(e.get("isCancelled") or e.get("cancelled"))}
    if ty == "Card":
        return {**base, "type": "card", "card": (e.get("card") or "").lower(),
                "player": p.get("name"), "player_id": p.get("id")}
    if ty == "Substitution":
        swap = e.get("swap") or [{}, {}]
        return {**base, "type": "sub", "in": swap[0].get("name"), "out": swap[1].get("name"),
                "injury": bool(e.get("injuredPlayerOut"))}
    if ty == "Half":
        return {**base, "type": "half", "label": e.get("halfStrShort")}
    if ty == "AddedTime":
        return {**base, "type": "added_time", "minutes": e.get("minutesAddedInput")}
    if ty == "VAR":
        return {**base, "type": "var", "text": (e.get("VAR") or {}).get("decision")}
    return None


def _lineup_side(s: dict) -> dict:
    def pl(p, starter):
        perf = p.get("performance") or {}
        lay = p.get("verticalLayout") or {}
        return {
            "id": p.get("id"), "name": p.get("name"), "last_name": p.get("lastName") or p.get("name"),
            "number": p.get("shirtNumber"), "rating": perf.get("rating"),
            "events": [ev.get("type") for ev in perf.get("events") or []],
            "sub": [{"min": se.get("time"), "type": se.get("type")}
                    for se in perf.get("substitutionEvents") or []],
            # координаты на поле 0..1 (снизу вверх), только у стартовых
            "x": lay.get("x") if starter else None, "y": lay.get("y") if starter else None,
            "photo": player_photo(p.get("id")),
        }
    return {
        "id": s.get("id"), "name": s.get("name"), "formation": s.get("formation"),
        "rating": s.get("rating"),
        "coach": (s.get("coach") or {}).get("name"),
        "starters": [pl(p, True) for p in s.get("starters") or []],
        "subs": [pl(p, False) for p in s.get("subs") or []],
        "unavailable": [{"name": p.get("name"),
                         "type": (p.get("unavailability") or {}).get("type"),
                         "expected_return": (p.get("unavailability") or {}).get("expectedReturn")}
                        for p in s.get("unavailable") or []],
    }


def _stats(periods: dict) -> dict:
    out = {}
    for period, block in (periods or {}).items():
        groups = []
        for g in block.get("stats") or []:
            items = [{"key": s.get("key"), "title": s.get("title"),
                      "home": (s.get("stats") or [None, None])[0],
                      "away": (s.get("stats") or [None, None])[1],
                      "highlight": s.get("highlighted")}
                     for s in g.get("stats") or [] if s.get("type") != "title"]
            if items:
                groups.append({"key": g.get("key"), "title": g.get("title"), "items": items})
        out[period] = groups
    return out


async def match(match_id: int) -> dict:
    m = await raw_match(match_id)
    st = (m.get("header") or {}).get("status") or {}
    live = bool(st.get("started")) and not st.get("finished")
    if live:  # на лайве перечитываем с коротким TTL
        m = await raw_match(match_id, live_hint=True)
        st = (m.get("header") or {}).get("status") or {}

    g = m.get("general") or {}
    c = m.get("content") or {}
    mf = c.get("matchFacts") or {}
    info = mf.get("infoBox") or {}
    teams = (m.get("header") or {}).get("teams") or [{}, {}]
    lineup = c.get("lineup") or {}
    home_id = (g.get("homeTeam") or {}).get("id")
    potm = mf.get("playerOfTheMatch") or {}
    h2h = c.get("h2h") or {}

    return {
        "id": int(g.get("matchId") or match_id),
        "utc": g.get("matchTimeUTCDate"),
        "tournament": g.get("leagueName"),
        "round": g.get("leagueRoundName"),
        "state": "finished" if st.get("finished") else "live" if st.get("started") else
                 "cancelled" if st.get("cancelled") else "scheduled",
        "minute": (st.get("liveTime") or {}).get("short") if live else None,
        "reason": (st.get("reason") or {}).get("short"),
        "home": {"id": teams[0].get("id"), "name": teams[0].get("name"),
                 "score": teams[0].get("score"), "logo": team_logo(teams[0].get("id"))},
        "away": {"id": teams[1].get("id"), "name": teams[1].get("name"),
                 "score": teams[1].get("score"), "logo": team_logo(teams[1].get("id"))},
        "stadium": (info.get("Stadium") or {}).get("name"),
        "city": (info.get("Stadium") or {}).get("city"),
        "referee": (info.get("Referee") or {}).get("text"),
        "attendance": info.get("Attendance"),
        "events": [x for x in (_event(e) for e in (mf.get("events") or {}).get("events") or []) if x],
        "lineups": {
            "confirmed": bool(lineup.get("homeTeam", {}).get("starters")),
            "home": _lineup_side(lineup.get("homeTeam") or {}),
            "away": _lineup_side(lineup.get("awayTeam") or {}),
        } if lineup else None,
        "stats": _stats((c.get("stats") or {}).get("Periods") or {}),
        "shots": [{
            "x": s.get("x"), "y": s.get("y"), "min": s.get("min"),
            "side": "home" if s.get("teamId") == home_id else "away",
            "player": s.get("playerName"), "xg": s.get("expectedGoals"),
            "outcome": s.get("eventType"),  # Goal / AttemptSaved / Miss / Post
            "situation": s.get("situation"), "body": s.get("shotType"),
        } for s in (c.get("shotmap") or {}).get("shots") or []],
        "momentum": ((c.get("momentum") or {}).get("main") or {}).get("data") or [],
        "potm": {"id": potm.get("id"), "name": (potm.get("name") or {}).get("fullName"),
                 "team": potm.get("teamName"), "rating": (potm.get("rating") or {}).get("num"),
                 "photo": player_photo(potm.get("id"))} if potm.get("id") else None,
        "highlights": (mf.get("highlights") or {}).get("url"),
        "form": [[{"r": f.get("resultString"), "score": f.get("score")} for f in side]
                 for side in mf.get("teamForm") or []],
        "h2h": {
            "summary": h2h.get("summary"),  # [победы хозяев, ничьи, победы гостей]
            "matches": [{
                "utc": (x.get("time") or {}).get("utcTime"),
                "league": (x.get("league") or {}).get("name"),
                "home": (x.get("home") or {}).get("name"), "away": (x.get("away") or {}).get("name"),
                "score": (x.get("status") or {}).get("scoreStr"),
                "finished": bool((x.get("status") or {}).get("finished")),
            } for x in h2h.get("matches") or []][:10],
        },
    }
