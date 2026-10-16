"""SofaScore — первый резерв. Только через SOCKS-туннель хоста и только curl_cffi
с impersonate="safari" (запасной "firefox133"; "chrome" ловит 403 challenge).

Матч у SofaScore разложен по 7 эндпоинтам. В лайве бережём источник:
каждый цикл — event + incidents, остальное (составы, статистика, удары,
давление) — раз в несколько циклов, best-players — после финала.
"""
import time
from datetime import datetime

from curl_cffi.requests import AsyncSession

from .. import config
from ..model import (ROLE_BY_POS, age_on, ctx_team, empty_match, empty_player, event, finish_match,
                     finish_player, formation_layout, img_flag, img_league, img_player, img_team, iso_utc,
                     lineup_player, person, resolve_player, result_for, stat_list, status)
from .base import NotFound, Source

BASE = "https://www.sofascore.com/api/v1"


class SofaScore(Source):
    name = "sofascore"
    timeout = config.SOFA_TIMEOUT

    def __init__(self):
        super().__init__()
        self.session = None
        self.impersonate = "safari"

    async def _fetch(self, url, params):
        if self.session is None:
            self.session = AsyncSession(proxies={"http": config.SOFA_PROXY, "https": config.SOFA_PROXY})
        r = await self.session.get(url, params=params, impersonate=self.impersonate, timeout=self.timeout,
                                   headers={"Accept": "application/json", "Referer": "https://www.sofascore.com/"})
        if r.status_code == 403 and self.impersonate == "safari":
            # challenge на отпечаток — пробуем запасной профиль в том же запросе
            self.impersonate = "firefox133"
            r = await self.session.get(url, params=params, impersonate=self.impersonate, timeout=self.timeout)
        if r.status_code == 404:
            raise NotFound(f"404 {url}")
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} ({self.impersonate})")
        return r.json()

    async def close(self):
        if self.session is not None:
            await self.session.close()

    # --- эндпоинты ---
    async def team_events(self, which: str, page: int = 0) -> dict:
        return await self.get(f"{BASE}/team/{config.SOFA_TEAM_ID}/events/{which}/{page}", kind=f"events_{which}")

    async def event(self, eid) -> dict:
        return await self.get(f"{BASE}/event/{eid}", kind="event")

    async def part(self, eid, name: str) -> dict | None:
        """incidents | lineups | statistics | shotmap | graph | best-players/summary; 404 → None."""
        try:
            return await self.get(f"{BASE}/event/{eid}/{name}", kind=name.split("/")[0])
        except NotFound:
            return None

    async def standings(self, ut: int, season: int) -> dict:
        return await self.get(f"{BASE}/unique-tournament/{ut}/season/{season}/standings/total", kind="standings")

    async def seasons(self, ut: int) -> dict:
        return await self.get(f"{BASE}/unique-tournament/{ut}/seasons", kind="seasons")

    async def players(self) -> dict:
        return await self.get(f"{BASE}/team/{config.SOFA_TEAM_ID}/players", kind="players")

    async def live_events(self) -> dict:
        """Все идущие матчи (~0,5 МБ) — только для поиска id чужого матча, результат кэшируется."""
        return await self.get(f"{BASE}/sport/football/events/live", kind="live_events")

    async def player(self, sid) -> dict:
        return await self.get(f"{BASE}/player/{sid}", kind="player")

    async def player_events(self, sid) -> dict:
        """Последние ~30 матчей игрока: оценка и минуты (statisticsMap), голы/передачи/карточки (incidentsMap)."""
        return await self.get(f"{BASE}/player/{sid}/events/last/0", kind="player_events")


# ---------- статус ----------

_PERIOD_START = {6: 0, 7: 45, 41: 90, 42: 105}


def _status(ev: dict, now: float | None = None) -> dict:
    st = ev.get("status") or {}
    code, ty = st.get("code"), st.get("type")
    desc = st.get("description")
    if ty == "finished":
        return status("finished", label={110: "AET", 120: "Pen"}.get(code, "FT"))
    if ty == "postponed" or code == 60:
        return status("postponed", label=desc)
    if ty in ("canceled", "cancelled") or code == 70:
        return status("cancelled", label=desc)
    if code in (91, 92) or ty == "interrupted":
        return status("abandoned", label=desc)
    if ty == "inprogress":
        if code == 31:
            return status("halftime", 45, label="HT")
        now = now or time.time()
        stt = ev.get("statusTime") or {}
        minute = added = None
        if stt.get("timestamp") is not None and stt.get("initial") is not None:
            secs = stt["initial"] + (now - stt["timestamp"])
            minute = int(secs // 60) + 1
            cap = int((stt.get("max") or 0) // 60)
            if cap and minute > cap:
                minute, added = cap, minute - cap
        elif (ev.get("time") or {}).get("currentPeriodStartTimestamp") and code in _PERIOD_START:
            start = _PERIOD_START[code]
            minute = start + int((now - ev["time"]["currentPeriodStartTimestamp"]) // 60) + 1
            cap = start + (45 if code in (6, 7) else 15)
            if minute > cap:
                minute, added = cap, minute - cap
        return status("live", minute, added, label=desc)
    return status("scheduled", label=desc)


# ---------- матч ----------

_STATS = {
    "ballPossession": "possession", "expectedGoals": "xg", "totalShotsOnGoal": "shots_total",
    "shotsOnGoal": "shots_on_target", "bigChanceCreated": "big_chances", "cornerKicks": "corners",
    "shotsOffGoal": "shots_off_target", "blockedScoringAttempt": "shots_blocked",
    "hitWoodwork": "shots_woodwork", "totalShotsInsideBox": "shots_inside_box",
    "totalShotsOutsideBox": "shots_outside_box", "expectedGoalsOnTarget": "xg_on_target",
    "passes": "passes_total", "accuratePasses": "passes_accurate", "accurateLongBalls": "long_balls_accurate",
    "accurateCross": "crosses_accurate", "touchesInOppBox": "touches_opp_box", "totalTackle": "tackles",
    "interceptionWon": "interceptions", "totalClearance": "clearances", "goalkeeperSaves": "saves",
    "fouls": "fouls", "offsides": "offsides", "yellowCards": "yellow_cards", "redCards": "red_cards",
}
_PERIODS = {"ALL": "all", "1ST": "first_half", "2ND": "second_half"}
_SHOT = {"goal": "goal", "save": "saved", "miss": "miss", "block": "blocked", "post": "post"}
_CARD = {"yellow": "yellow", "red": "red", "yellowRed": "second_yellow"}
_POS = {"G": "GK", "D": "DF", "M": "MF", "F": "FW"}


def _stats(raw: dict | None) -> dict | None:
    if not raw:
        return None
    out = {}
    for per in raw.get("statistics") or []:
        our = _PERIODS.get(per.get("period"))
        if not our:
            continue
        pairs = {}
        for g in per.get("groups") or []:
            for it in g.get("statisticsItems") or []:
                k = _STATS.get(it.get("key"))
                if k and k not in pairs:
                    pairs[k] = (it.get("homeValue", it.get("home")), it.get("awayValue", it.get("away")))
        out[our] = stat_list(pairs)
    return out if out.get("all") else None


def _person(ctx, p: dict | None, side=None):
    if not p:
        return None
    name = p.get("name")
    return person(name=name, fotmob_id=resolve_player(ctx, side, p.get("jerseyNumber"), name))


def normalize_match(b: dict, ctx: dict | None = None, now: float | None = None) -> dict:
    """b = {"event": ..., "incidents": ..., "lineups": ..., "statistics": ..., "shotmap": ..., "graph": ..., "best": ...}"""
    ctx = ctx or {}
    ev = (b.get("event") or {}).get("event") or {}
    m = empty_match()
    eid = ev.get("id")
    fm_id = ctx.get("match_id")
    m["id"] = fm_id or (f"sofascore:{eid}" if eid else None)
    m["ids"].update(fotmob=fm_id, sofascore=eid)
    m["kickoff"] = iso_utc(ev.get("startTimestamp"))
    m["status"] = _status(ev, now)
    ut = (ev.get("tournament") or {}).get("uniqueTournament") or {}
    lid = config.SOFA_TO_FM_LEAGUE.get(ut.get("id"))
    m["tournament"] = {"id": lid, "name": ut.get("name") or (ev.get("tournament") or {}).get("name"),
                       "round": str((ev.get("roundInfo") or {}).get("round") or "") or None, "logo": img_league(lid)}
    v = ev.get("venue") or {}
    vname = v.get("name") or (v.get("stadium") or {}).get("name")
    if vname:
        m["venue"] = {"name": vname, "city": (v.get("city") or {}).get("name")}
    m["referee"] = (ev.get("referee") or {}).get("name")
    m["attendance"] = ev.get("attendance")
    started = m["status"]["state"] not in ("scheduled", "postponed", "cancelled")
    for key in ("home", "away"):
        t = ev.get(f"{key}Team") or {}
        sc = ev.get(f"{key}Score") or {}
        fm_team = ctx_team(ctx, t.get("id"))
        m[key].update(id=fm_team, name=t.get("name"), short=t.get("shortName") or t.get("name"),
                      score=sc.get("current") if started else None,
                      ht_score=sc.get("period1"), logo=img_team(fm_team))

    subs_in, subs_out = {}, {}
    for i in (b.get("incidents") or {}).get("incidents") or []:
        ty, cls = i.get("incidentType"), i.get("incidentClass")
        side = "home" if i.get("isHome") else "away"
        mi, add = i.get("time"), i.get("addedTime") if (i.get("addedTime") or 0) < 999 else None
        if ty == "goal":
            m["events"].append(event(
                "goal", mi, add, side, player=_person(ctx, i.get("player"), side),
                assist=_person(ctx, i.get("assist1"), side), own_goal=cls == "ownGoal",
                penalty=cls == "penalty", shootout=False,
                score=[i.get("homeScore"), i.get("awayScore")]))
        elif ty == "card":
            m["events"].append(event("card", mi, add, side, card=_CARD.get(cls, "yellow"),
                                     player=_person(ctx, i.get("player"), side), reason=i.get("reason")))
        elif ty == "substitution":
            pin, pout = i.get("playerIn") or {}, i.get("playerOut") or {}
            subs_in[pin.get("id")], subs_out[pout.get("id")] = mi, mi
            m["events"].append(event("sub", mi, add, side, player_in=_person(ctx, pin, side),
                                     player_out=_person(ctx, pout, side), injury=bool(i.get("injury"))))
        elif ty == "varDecision":
            m["events"].append(event("var", mi, add, side, player=_person(ctx, i.get("player"), side),
                                     decision=cls, confirmed=i.get("confirmed")))
        elif ty == "period":
            m["events"].append(event("period", mi, None, None, label=i.get("text"),
                                     score=[i.get("homeScore"), i.get("awayScore")]))
        elif ty == "injuryTime":
            m["events"].append(event("added_time", mi, None, None, minutes=i.get("length")))
        elif ty == "inGamePenalty" and cls == "missed":
            m["events"].append(event("penalty_missed", mi, add, side, player=_person(ctx, i.get("player"), side)))

    lu = b.get("lineups") or {}
    if (lu.get("home") or {}).get("players"):
        m["lineups"] = {"confirmed": bool(lu.get("confirmed"))}
        for key in ("home", "away"):
            t = lu.get(key) or {}
            players = t.get("players") or []
            starters = [p for p in players if not p.get("substitute")][:11]
            bench = [p for p in players if p.get("substitute")]
            layout = formation_layout(t.get("formation"), len(starters)) or [(None, None)] * len(starters)

            def pl(p, xy):
                pp = p.get("player") or {}
                num = p.get("shirtNumber") or p.get("jerseyNumber") or pp.get("jerseyNumber")
                return lineup_player(
                    pp.get("name"), num, fotmob_id=resolve_player(ctx, key, num, pp.get("name")),
                    position=_POS.get(p.get("position") or pp.get("position")),
                    rating=(p.get("statistics") or {}).get("rating"), x=xy[0], y=xy[1],
                    captain=p.get("captain"), sub_in=subs_in.get(pp.get("id")), sub_out=subs_out.get(pp.get("id")),
                    source_id=pp.get("id"))

            m["lineups"][key] = {
                "team_id": m[key]["id"], "formation": t.get("formation"), "rating": None, "coach": None,
                "starters": [pl(p, xy) for p, xy in zip(starters, layout)],
                "subs": [pl(p, (None, None)) for p in bench],
                "unavailable": [{
                    "id": resolve_player(ctx, key, None, (mp.get("player") or {}).get("name")),
                    "name": (mp.get("player") or {}).get("name"),
                    "photo": img_player(resolve_player(ctx, key, None, (mp.get("player") or {}).get("name"))),
                    "type": mp.get("description") or mp.get("type"),
                    "expected_return": iso_utc(mp.get("expectedEndDate")) if mp.get("expectedEndDate") else None,
                } for mp in t.get("missingPlayers") or []],
            }

    m["stats"] = _stats(b.get("statistics"))

    for s in (b.get("shotmap") or {}).get("shotmap") or []:
        pc = s.get("playerCoordinates") or {}
        side = "home" if s.get("isHome") else "away"
        m["shots"].append({
            # у SofaScore x — расстояние от атакуемой линии ворот в %, y зеркален относительно FotMob
            "x": round(100 - (pc.get("x") or 0), 1), "y": round(100 - (pc.get("y") or 0), 1),
            "minute": s.get("time"), "added": s.get("addedTime"), "side": side,
            "player": _person(ctx, s.get("player"), side),
            "outcome": _SHOT.get(s.get("shotType"), "miss"), "own_goal": s.get("goalType") == "own",
            "xg": round(s["xg"], 3) if s.get("xg") is not None else None,
            "xgot": round(s["xgot"], 3) if s.get("xgot") else None,
            "situation": s.get("situation"), "body": s.get("bodyPart"), "period": None,
        })
    m["shots"].sort(key=lambda s: ((s["minute"] or 0), (s["added"] or 0)))

    m["momentum"] = [{"minute": p.get("minute"), "value": p.get("value")}
                     for p in (b.get("graph") or {}).get("graphPoints") or [] if p.get("value") is not None]

    best = b.get("best") or {}
    potm = best.get("playerOfTheMatch") or {}
    if potm.get("player"):
        pid = (potm["player"] or {}).get("id")
        side = "home" if any((x.get("player") or {}).get("id") == pid for x in best.get("bestHomeTeamPlayers") or []) \
            else "away"
        m["potm"] = {**_person(ctx, potm["player"], side), "side": side,
                     "rating": float(potm.get("value")) if potm.get("value") else None}
    return finish_match(m, "sofascore")


# ---------- календарь ----------

def normalize_fixtures(raw_events: list[dict], ctx: dict | None = None, now: float | None = None) -> list:
    ctx = ctx or {}
    matches = ctx.get("matches") or {}
    out, seen = [], set()
    for ev in raw_events:
        ut = ((ev.get("tournament") or {}).get("uniqueTournament") or {}).get("id")
        lid = config.SOFA_TO_FM_LEAGUE.get(ut)
        if not lid or ev.get("id") in seen:
            continue
        seen.add(ev.get("id"))
        st = _status(ev, now)
        started = st["state"] not in ("scheduled", "postponed", "cancelled")
        h, a = ev.get("homeTeam") or {}, ev.get("awayTeam") or {}
        hs = (ev.get("homeScore") or {}).get("current") if started else None
        as_ = (ev.get("awayScore") or {}).get("current") if started else None
        hid, aid = ctx_team(ctx, h.get("id")), ctx_team(ctx, a.get("id"))
        if h.get("id") == config.SOFA_TEAM_ID:
            hid = config.TEAM_ID
        if a.get("id") == config.SOFA_TEAM_ID:
            aid = config.TEAM_ID
        fm = matches.get(str(ev.get("id")))
        out.append({
            "id": int(fm) if fm else f"sofascore:{ev.get('id')}",
            "ids": {"fotmob": int(fm) if fm else None, "sofascore": ev.get("id"), "espn": None, "livescore": None},
            "kickoff": iso_utc(ev.get("startTimestamp")),
            "tournament": {"id": lid, "name": config.LEAGUES[lid]["name"],
                           "round": str((ev.get("roundInfo") or {}).get("round") or "") or None,
                           "logo": img_league(lid)},
            "home": {"id": hid, "name": h.get("name"), "score": hs, "logo": img_team(hid)},
            "away": {"id": aid, "name": a.get("name"), "score": as_, "logo": img_team(aid)},
            "status": st,
            "is_home": h.get("id") == config.SOFA_TEAM_ID,
            "result": result_for(config.SOFA_TEAM_ID, h.get("id"), hs, as_) if st["finished"] else None,
        })
    out.sort(key=lambda x: x["kickoff"] or "")
    return out


# ---------- таблицы ----------

def normalize_table(raw: dict, lid: int, ctx: dict | None = None) -> dict | None:
    st = (raw.get("standings") or [None])[0]
    if not st:
        return None
    rows = []
    for r in st.get("rows") or []:
        t = r.get("team") or {}
        fm = config.TEAM_ID if t.get("id") == config.SOFA_TEAM_ID else ctx_team(ctx, t.get("id"))
        prom = r.get("promotion") or {}
        rows.append({
            "pos": r.get("position"),
            "team": {"id": fm, "name": t.get("name"), "short": t.get("shortName") or t.get("name"), "logo": img_team(fm)},
            "played": r.get("matches"), "w": r.get("wins"), "d": r.get("draws"), "l": r.get("losses"),
            "gf": r.get("scoresFor"), "ga": r.get("scoresAgainst"),
            "gd": (r.get("scoresFor") or 0) - (r.get("scoresAgainst") or 0), "pts": r.get("points"),
            "zone": {"label": prom.get("text"), "color": None} if prom else None,
            "is_us": t.get("id") == config.SOFA_TEAM_ID,
        })
    return {"league": {"id": lid, "name": config.LEAGUES[lid]["name"], "logo": img_league(lid)}, "rows": rows}


# ---------- команда ----------

def normalize_team(raw: dict, ctx: dict | None = None) -> dict:
    lines = {"G": "goalkeepers", "D": "defenders", "M": "midfielders", "F": "attackers"}
    squad = {v: [] for v in lines.values()}
    for it in raw.get("players") or []:
        p = it.get("player") or {}
        line = lines.get(p.get("position"))
        if not line:
            continue
        fm = resolve_player(ctx, None, None, p.get("name"))
        country = p.get("country") or {}
        squad[line].append({
            "id": fm, "name": p.get("name"), "number": p.get("jerseyNumber") or p.get("shirtNumber"),
            "position": _POS.get(p.get("position")), "age": None,
            "birth": iso_utc(p.get("dateOfBirthTimestamp"))[:10] if p.get("dateOfBirthTimestamp") else None,
            "height": p.get("height"),
            "country": {"code": country.get("alpha3"), "name": country.get("name"), "flag": img_flag(country.get("alpha2"))},
            "photo": img_player(fm), "rating": None, "goals": None, "assists": None, "yellow": None, "red": None,
            "value_eur": (p.get("proposedMarketValueRaw") or {}).get("value"), "injured": None,
        })
    avail = ["squad"] + (["player_photos"] if any(p["photo"] for ln in squad.values() for p in ln) else [])
    return {"team": {"id": config.TEAM_ID, "name": "Real Madrid", "logo": img_team(config.TEAM_ID)},
            "venue": None, "coach": None, "squad": squad, "injuries": [], "leaders": None, "transfers": None,
            "source": "sofascore", "available": avail}


# ---------- игрок (резерв карточки) ----------

# подробные позиции SofaScore → коды FotMob
_POS_DETAILED = {"GK": "GK", "DC": "CB", "DL": "LB", "DR": "RB", "DM": "DM", "MC": "CM", "ML": "LM", "MR": "RM",
                 "AM": "AM", "LW": "LW", "RW": "RW", "ST": "ST", "CF": "ST"}
_FOOT = {"right": "right", "left": "left", "both": "both"}


def _team_fm(ctx, t: dict | None) -> dict | None:
    """Команда SofaScore → наша ссылка: id FotMob из сопоставления (нет — без эмблемы)."""
    if not t:
        return None
    sid = t.get("id")
    fm = config.TEAM_ID if sid == config.SOFA_TEAM_ID else ctx_team(ctx, sid)
    fm = int(fm) if fm not in (None, "") and str(fm).isdigit() else None
    return {"id": fm, "name": t.get("name"), "logo": img_team(fm)}


def normalize_player(raw: dict, last: dict | None, ctx: dict | None = None, now: datetime | None = None) -> dict:
    """raw — /player/{id}, last — /player/{id}/events/last/0. Сезон — сумма по этим матчам (≈30 последних),
    поэтому помечен partial: у SofaScore полная статистика лежит в отдельном запросе на каждый турнир."""
    ctx = ctx or {}
    pl = raw.get("player") or {}
    p = empty_player(ctx.get("fotmob_id"))
    p["ids"]["sofascore"] = pl.get("id")
    p["name"] = pl.get("name")
    p["short_name"] = pl.get("shortName")
    n = pl.get("shirtNumber") or pl.get("jerseyNumber")
    p["number"] = int(n) if str(n or "").isdigit() else None
    codes = [_POS_DETAILED.get(c) for c in pl.get("positionsDetailed") or []]
    p["positions"] = [c for c in dict.fromkeys(codes) if c]
    p["position"] = p["positions"][0] if p["positions"] else None
    p["role"] = ROLE_BY_POS.get(p["position"] or "") or _POS.get(pl.get("position"))
    p["height"] = pl.get("height")
    p["foot"] = _FOOT.get((pl.get("preferredFoot") or "").lower())
    ts_birth = pl.get("dateOfBirthTimestamp")
    p["birth"] = iso_utc(ts_birth)[:10] if ts_birth is not None else None
    p["age"] = age_on(p["birth"], now)
    p["value_eur"] = (pl.get("proposedMarketValueRaw") or {}).get("value") or pl.get("proposedMarketValue")
    cu = pl.get("contractUntilTimestamp")
    p["contract_until"] = iso_utc(cu)[:10] if cu else None
    c = pl.get("country") or {}
    if c.get("name"):
        p["country"] = {"code": c.get("alpha3"), "name": c.get("name"), "flag": img_flag(c.get("alpha2")),
                        "team_id": None}
    team = _team_fm(ctx, pl.get("team"))
    if team:
        p["team"] = {**team, "on_loan": False}
    club_sid = (pl.get("team") or {}).get("id")

    last = last or {}
    stats, inc = last.get("statisticsMap") or {}, last.get("incidentsMap") or {}
    played_for = last.get("playedForTeamMap") or {}
    matches = ctx.get("matches") or {}
    rows = []
    for e in last.get("events") or []:
        if ((e.get("status") or {}).get("type")) != "finished":
            continue
        k = str(e.get("id"))
        st = stats.get(k) or {}
        if not st.get("minutesPlayed"):
            continue  # на поле не выходил
        tid = played_for.get(k)
        home = (e.get("homeTeam") or {}).get("id") == tid
        hs, as_ = (e.get("homeScore") or {}).get("current"), (e.get("awayScore") or {}).get("current")
        ours, theirs = (hs, as_) if home else (as_, hs)
        res = None if ours is None or theirs is None else "W" if ours > theirs else "L" if ours < theirs else "D"
        ut = ((e.get("tournament") or {}).get("uniqueTournament") or {})
        lid = config.SOFA_TO_FM_LEAGUE.get(ut.get("id"))
        im = inc.get(k) or {}
        fm_match = matches.get(k)
        rows.append({
            "match_id": int(fm_match) if str(fm_match or "").isdigit() else None,
            "kickoff": iso_utc(e.get("startTimestamp")),
            "tournament": {"id": lid, "name": ut.get("name") or (e.get("tournament") or {}).get("name"),
                           "logo": img_league(lid)},
            "team": _team_fm(ctx, e.get("homeTeam") if home else e.get("awayTeam")),
            "opponent": _team_fm(ctx, e.get("awayTeam") if home else e.get("homeTeam")),
            "home": home, "score": [hs, as_], "result": res, "conceded": theirs,
            "played": True, "bench": False, "minutes": st.get("minutesPlayed"),
            "goals": im.get("goals") or 0, "assists": im.get("assists") or 0,
            "yellow": im.get("yellowCards") or 0, "red": (im.get("redCards") or 0) + (im.get("yellowRedCards") or 0),
            "rating": round(float(st["rating"]), 2) if st.get("rating") else None,
            "potm": False,
            "_season": (e.get("season") or {}).get("year"), "_club": tid == club_sid, "_ut": ut.get("id"),
        })
    rows.sort(key=lambda r: r["kickoff"] or "", reverse=True)

    club = [r for r in rows if r["_club"]]
    if club:
        year = club[0]["_season"]
        groups: dict = {}
        for r in club:
            if r["_season"] == year:
                groups.setdefault(r["_ut"], []).append(r)
        keeper = p["role"] == "GK"
        tours = []
        for g in groups.values():
            rated = [r["rating"] for r in g if r["rating"]]
            row = {"league": g[0]["tournament"], "matches": len(g), "started": None,
                   "minutes": sum(r["minutes"] or 0 for r in g),
                   "goals": sum(r["goals"] for r in g), "assists": sum(r["assists"] for r in g),
                   "rating": round(sum(rated) / len(rated), 2) if rated else None,
                   "yellow": sum(r["yellow"] for r in g), "red": sum(r["red"] for r in g),
                   "clean_sheets": sum(1 for r in g if r["conceded"] == 0) if keeper else None,
                   "conceded": sum(r["conceded"] or 0 for r in g) if keeper else None, "saves": None}
            tours.append(row)
        tours.sort(key=lambda t: -t["matches"])
        allr = [r["rating"] for g in groups.values() for r in g if r["rating"]]
        totals = {k: sum(t[k] for t in tours) for k in ("matches", "minutes", "goals", "assists", "yellow", "red")}
        totals["rating"] = round(sum(allr) / len(allr), 2) if allr else None
        if keeper:
            totals["clean_sheets"] = sum(t["clean_sheets"] for t in tours)
            totals["conceded"] = sum(t["conceded"] for t in tours)
            totals["saves"] = None
        y = str(year or "")
        name = f"20{y[:2]}/20{y[3:]}" if len(y) == 5 and y[2] == "/" else y or None
        p["season"] = {"name": name, "team": p["team"] and {k: p["team"][k] for k in ("id", "name", "logo")},
                       "totals": totals, "tournaments": tours, "partial": True}
    for r in rows:
        for k in ("_season", "_club", "_ut"):
            r.pop(k, None)
    p["recent"] = rows[:10]
    return finish_player(p, "sofascore")
