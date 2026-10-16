"""ESPN — второй резерв (без ключа). Нет оценок, xG, карты ударов, давления и координат
игроков на поле — эти поля отдаются пустыми, `available` это отражает."""
import re

from .. import config
from ..model import (ctx_team, empty_match, event, finish_match, img_league, img_player, img_team, iso_utc,
                     lineup_player, person, resolve_player, result_for, stat_list, status)
from .base import HttpxSource

SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
STANDINGS = "https://site.web.api.espn.com/apis/v2/sports/soccer"


class ESPN(HttpxSource):
    name = "espn"

    async def schedule(self, slug: str, upcoming: bool) -> dict:
        params = {"fixture": "true"} if upcoming else None
        return await self.get(f"{SITE}/{slug}/teams/{config.ESPN_TEAM_ID}/schedule", params,
                              kind="schedule_next" if upcoming else "schedule_past")

    async def summary(self, slug: str, event_id) -> dict:
        return await self.get(f"{SITE}/{slug}/summary", {"event": event_id}, kind="summary")

    async def standings(self, slug: str) -> dict:
        return await self.get(f"{STANDINGS}/{slug}/standings", kind="standings")

    async def roster(self, slug: str = "esp.1") -> dict:
        return await self.get(f"{SITE}/{slug}/teams/{config.ESPN_TEAM_ID}/roster", kind="roster")


_CLOCK = re.compile(r"(\d+)'?\s*(?:\+\s*(\d+))?")


def _clock(v) -> tuple[int | None, int | None]:
    m = _CLOCK.search(str(v or ""))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None


def _status(st: dict) -> dict:
    t = st.get("type") or {}
    name, state = t.get("name") or "", t.get("state")
    if "POSTPONED" in name:
        return status("postponed", label=t.get("shortDetail"))
    if "CANCELED" in name or "CANCELLED" in name:
        return status("cancelled", label=t.get("shortDetail"))
    if "ABANDONED" in name:
        return status("abandoned", label=t.get("shortDetail"))
    if state == "post" or t.get("completed"):
        return status("finished", label=t.get("shortDetail") or "FT")
    if state == "in":
        if "HALFTIME" in name:
            return status("halftime", 45, label="HT")
        mi, add = _clock(st.get("displayClock"))
        return status("live", mi, add, label=st.get("displayClock"))
    return status("scheduled", label=t.get("shortDetail"))


def _score(v):
    if isinstance(v, dict):
        v = v.get("displayValue", v.get("value"))
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


_STATS = {
    "possessionPct": "possession", "totalShots": "shots_total", "shotsOnTarget": "shots_on_target",
    "blockedShots": "shots_blocked", "wonCorners": "corners", "totalPasses": "passes_total",
    "accuratePasses": "passes_accurate", "accurateLongBalls": "long_balls_accurate",
    "accurateCrosses": "crosses_accurate", "totalTackles": "tackles", "interceptions": "interceptions",
    "totalClearance": "clearances", "saves": "saves", "foulsCommitted": "fouls", "offsides": "offsides",
    "yellowCards": "yellow_cards", "redCards": "red_cards",
}


def normalize_match(raw: dict, ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    m = empty_match()
    comp = ((raw.get("header") or {}).get("competitions") or [{}])[0]
    eid = comp.get("id") or (raw.get("header") or {}).get("id")
    fm_id = ctx.get("match_id")
    m["id"] = fm_id or (f"espn:{eid}" if eid else None)
    m["ids"].update(fotmob=fm_id, espn=eid)
    m["kickoff"] = iso_utc(comp.get("date"))
    m["status"] = _status(comp.get("status") or {})
    slug = ((raw.get("header") or {}).get("league") or {}).get("slug")
    lid = config.ESPN_TO_FM_LEAGUE.get(slug)
    m["tournament"] = {"id": lid, "name": ((raw.get("header") or {}).get("league") or {}).get("name"),
                       "round": None, "logo": img_league(lid)}
    gi = raw.get("gameInfo") or {}
    v = gi.get("venue") or {}
    if v.get("fullName"):
        m["venue"] = {"name": v.get("fullName"), "city": (v.get("address") or {}).get("city")}
    m["attendance"] = gi.get("attendance")
    ref = next((o for o in gi.get("officials") or [] if "referee" in str((o.get("position") or {}).get("name", "")).lower()
                or o.get("order") == 1), None)
    m["referee"] = (ref or {}).get("displayName") or (ref or {}).get("fullName")

    started = m["status"]["state"] not in ("scheduled", "postponed", "cancelled")
    side_of = {}
    for c in comp.get("competitors") or []:
        key = c.get("homeAway")
        if key not in ("home", "away"):
            continue
        t = c.get("team") or {}
        side_of[str(t.get("id"))] = key
        fm_team = config.TEAM_ID if str(t.get("id")) == config.ESPN_TEAM_ID else ctx_team(ctx, t.get("id"))
        ls = c.get("linescores") or []
        m[key].update(id=fm_team, name=t.get("displayName") or t.get("name"),
                      short=t.get("shortDisplayName") or t.get("abbreviation"),
                      score=_score(c.get("score")) if started else None,
                      ht_score=_score(ls[0]) if ls else None, logo=img_team(fm_team))

    score = [0, 0]
    subs_in, subs_out = {}, {}
    for k in raw.get("keyEvents") or []:
        ty = ((k.get("type") or {}).get("type") or "").lower()
        mi, add = _clock((k.get("clock") or {}).get("displayValue"))
        side = side_of.get(str((k.get("team") or {}).get("id")))
        parts = [(p.get("athlete") or {}) for p in k.get("participants") or []]
        nm = lambda i: parts[i].get("displayName") if len(parts) > i else None  # noqa: E731
        if k.get("scoringPlay") or ty.startswith("goal") or ty in ("penalty---scored", "own-goal"):
            if side:
                score[0 if side == "home" else 1] += 1
            own = "own" in ty
            m["events"].append(event(
                "goal", mi, add, side,
                player=person(name=nm(0), fotmob_id=resolve_player(ctx, side, None, nm(0))),
                assist=person(name=nm(1), fotmob_id=resolve_player(ctx, side, None, nm(1))) if nm(1) and not own else None,
                own_goal=own, penalty="penalty" in ty, shootout=False, score=list(score)))
        elif ty in ("yellow-card", "red-card"):
            card = "red" if ty == "red-card" else "yellow"
            if card == "red" and "second yellow" in (k.get("text") or "").lower():
                card = "second_yellow"
            m["events"].append(event("card", mi, add, side, card=card,
                                     player=person(name=nm(0), fotmob_id=resolve_player(ctx, side, None, nm(0))),
                                     reason=None))
        elif ty == "substitution":
            subs_in[nm(0)], subs_out[nm(1)] = mi, mi
            m["events"].append(event(
                "sub", mi, add, side,
                player_in=person(name=nm(0), fotmob_id=resolve_player(ctx, side, None, nm(0))),
                player_out=person(name=nm(1), fotmob_id=resolve_player(ctx, side, None, nm(1))),
                injury="injury" in (k.get("text") or "").lower()))
        elif ty in ("halftime", "end-regular-time"):
            m["events"].append(event("period", 45 if ty == "halftime" else 90, None, None,
                                     label="HT" if ty == "halftime" else "FT", score=list(score)))
    rosters = raw.get("rosters") or []
    if any(r.get("roster") for r in rosters):
        m["lineups"] = {"confirmed": True}
        for r in rosters:
            key = r.get("homeAway")
            if key not in ("home", "away"):
                continue

            def pl(x):
                a = x.get("athlete") or {}
                name = a.get("displayName")
                return lineup_player(
                    name, x.get("jersey"), fotmob_id=resolve_player(ctx, key, x.get("jersey"), name),
                    position=((x.get("position") or {}).get("abbreviation")), rating=None, x=None, y=None,
                    captain=False, sub_in=subs_in.get(name), sub_out=subs_out.get(name), source_id=a.get("id"))

            roster = r.get("roster") or []
            m["lineups"][key] = {
                "team_id": m[key]["id"], "formation": r.get("formation"), "rating": None, "coach": None,
                "starters": [pl(x) for x in sorted((x for x in roster if x.get("starter")),
                                                    key=lambda x: int(x.get("formationPlace") or 99))],
                "subs": [pl(x) for x in roster if not x.get("starter")],
                "unavailable": [],
            }
        if "away" not in m["lineups"] or "home" not in m["lineups"]:
            m["lineups"] = None

    teams = (raw.get("boxscore") or {}).get("teams") or []
    pairs = {}
    by_side = {}
    for t in teams:
        key = side_of.get(str((t.get("team") or {}).get("id")))
        if key:
            by_side[key] = {s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}
    if "home" in by_side and "away" in by_side:
        for src, our in _STATS.items():
            if src in by_side["home"] or src in by_side["away"]:
                pairs[our] = (by_side["home"].get(src), by_side["away"].get(src))
        st = stat_list(pairs)
        m["stats"] = {"all": st, "first_half": [], "second_half": []} if st else None

    form = {}
    for t in raw.get("lastFiveGames") or []:
        key = side_of.get(str((t.get("team") or {}).get("id")))
        if key:
            form[key] = [{"result": e.get("gameResult"), "score": e.get("score"), "kickoff": iso_utc(e.get("gameDate"))}
                         for e in t.get("events") or []]
    if len(form) == 2:
        m["form"] = form
    return finish_match(m, "espn")


def normalize_fixtures(schedules: dict[str, list[dict]], ctx: dict | None = None) -> list:
    """schedules = {slug: [schedule_json, ...]} (прошедшие и будущие)."""
    ctx = ctx or {}
    matches = ctx.get("matches") or {}
    out, seen = [], set()
    for slug, payloads in schedules.items():
        lid = config.ESPN_TO_FM_LEAGUE.get(slug)
        if not lid:
            continue
        for payload in payloads:
            for ev in (payload or {}).get("events") or []:
                if ev.get("id") in seen:
                    continue
                seen.add(ev.get("id"))
                comp = (ev.get("competitions") or [{}])[0]
                st = _status(comp.get("status") or ev.get("status") or {})
                started = st["state"] not in ("scheduled", "postponed", "cancelled")
                sides = {}
                for c in comp.get("competitors") or []:
                    t = c.get("team") or {}
                    tid = str(t.get("id"))
                    fm = config.TEAM_ID if tid == config.ESPN_TEAM_ID else ctx_team(ctx, tid)
                    sides[c.get("homeAway")] = {"id": fm, "espn_id": tid, "name": t.get("displayName"),
                                                "score": _score(c.get("score")) if started else None,
                                                "logo": img_team(fm)}
                h, a = sides.get("home") or {}, sides.get("away") or {}
                fm_match = matches.get(str(ev.get("id")))
                out.append({
                    "id": int(fm_match) if fm_match else f"espn:{ev.get('id')}",
                    "ids": {"fotmob": int(fm_match) if fm_match else None, "sofascore": None,
                            "espn": ev.get("id"), "livescore": None, "espn_league": slug},
                    "kickoff": iso_utc(comp.get("date") or ev.get("date")),
                    "tournament": {"id": lid, "name": config.LEAGUES[lid]["name"], "round": None,
                                   "logo": img_league(lid)},
                    "home": {k: h.get(k) for k in ("id", "name", "score", "logo")},
                    "away": {k: a.get(k) for k in ("id", "name", "score", "logo")},
                    "_espn_team_ids": [h.get("espn_id"), a.get("espn_id")],
                    "status": st,
                    "is_home": h.get("espn_id") == config.ESPN_TEAM_ID,
                    "result": result_for(config.ESPN_TEAM_ID, h.get("espn_id"), h.get("score"), a.get("score"))
                    if st["finished"] else None,
                })
    out.sort(key=lambda x: x["kickoff"] or "")
    return out


def normalize_table(raw: dict, lid: int, ctx: dict | None = None) -> dict | None:
    ch = (raw.get("children") or [None])[0]
    if not ch:
        return None
    entries = (ch.get("standings") or {}).get("entries") or []
    rows = []
    for e in entries:
        t = e.get("team") or {}
        s = {x.get("name"): x.get("value") for x in e.get("stats") or []}
        fm = config.TEAM_ID if str(t.get("id")) == config.ESPN_TEAM_ID else ctx_team(ctx, t.get("id"))
        note = e.get("note") or {}
        rows.append({
            "pos": int(s.get("rank") or 0) or None,
            "team": {"id": fm, "name": t.get("displayName"), "short": t.get("shortDisplayName") or t.get("displayName"),
                     "logo": img_team(fm)},
            "played": _score(s.get("gamesPlayed")), "w": _score(s.get("wins")), "d": _score(s.get("ties")),
            "l": _score(s.get("losses")), "gf": _score(s.get("pointsFor")), "ga": _score(s.get("pointsAgainst")),
            "gd": _score(s.get("pointDifferential")), "pts": _score(s.get("points")),
            "zone": {"label": note.get("description"), "color": "#" + note["color"].lstrip("#") if note.get("color") else None}
            if note else None,
            "is_us": str(t.get("id")) == config.ESPN_TEAM_ID,
        })
    rows.sort(key=lambda r: r["pos"] or 999)
    return {"league": {"id": lid, "name": config.LEAGUES[lid]["name"], "logo": img_league(lid)}, "rows": rows}


def normalize_team(raw: dict, ctx: dict | None = None) -> dict:
    lines = {"G": "goalkeepers", "D": "defenders", "M": "midfielders", "F": "attackers"}
    squad = {v: [] for v in lines.values()}
    injuries = []
    for a in raw.get("athletes") or []:
        pos = ((a.get("position") or {}).get("abbreviation") or "")[:1].upper()
        line = lines.get(pos)
        if not line:
            continue
        name = a.get("displayName")
        fm = resolve_player(ctx, None, None, name)
        inj = a.get("injuries") or []
        squad[line].append({
            "id": fm, "name": name, "number": _score(a.get("jersey")), "position": (a.get("position") or {}).get("abbreviation"),
            "age": a.get("age"), "birth": (a.get("dateOfBirth") or "")[:10] or None, "height": None,
            "country": {"code": None, "name": a.get("citizenship"), "flag": None},
            "photo": img_player(fm), "rating": None, "goals": None, "assists": None, "yellow": None, "red": None,
            "value_eur": None, "injured": bool(inj),
        })
        if inj:
            injuries.append({"id": fm, "name": name, "photo": img_player(fm),
                             "type": (inj[0].get("type") or {}).get("description") or inj[0].get("status"),
                             "expected_return": None})
    avail = ["squad"] + (["player_photos"] if any(p["photo"] for ln in squad.values() for p in ln) else [])
    if injuries:
        avail.append("injuries")
    return {"team": {"id": config.TEAM_ID, "name": "Real Madrid", "logo": img_team(config.TEAM_ID)},
            "venue": None, "coach": None, "squad": squad, "injuries": injuries, "leaders": None, "transfers": None,
            "source": "espn", "available": avail}
