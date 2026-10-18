"""FotMob — основной источник и канонические id.

Один запрос teams?id=8633 даёт календарь, таблицы (Ла Лига, ЛЧ), состав, травмы,
лидеров и трансферы. matchDetails — всё по матчу одним ответом. playerData — карточка игрока.
"""
import json
import re
from datetime import datetime, timezone

from .. import config
from ..model import (country_ref, venue as venue_ref, ROLE_BY_POS, age_on, empty_match, empty_player, event, finish_match, finish_player,
                     img_flag, img_league, img_player, img_team, iso_utc, lineup_player, num, person,
                     result_for, stat_list, status)
from .base import HttpxSource, NotFound

BASE = "https://www.fotmob.com/api/data"
API = "https://www.fotmob.com/api"
# текстовая трансляция (Opta): FotMob сам ходит за файлом по ltcUrl; русского нет — только английский
LTC_URL = "http://data.fotmob.com/webcl/ltc/gsm/{id}_{lang}.json.gz"


class FotMob(HttpxSource):
    name = "fotmob"

    async def team(self, team_id: int = config.TEAM_ID) -> dict:
        return await self.get(f"{BASE}/teams", {"id": team_id}, kind="team")

    async def match(self, match_id) -> dict:
        return await self.get(f"{BASE}/matchDetails", {"matchId": match_id}, kind="match")

    async def matches_on(self, yyyymmdd: str) -> dict:
        return await self.get(f"{BASE}/matches", {"date": yyyymmdd}, kind="matches_by_date")

    # --- редкие дополнительные запросы экрана матча (сборщик: tick_extras) ---

    async def insights(self, match_id, url_template: str, languages: list[str] | None = None) -> dict:
        """«Интересные факты» сразу по-русски: FotMob сам берёт файл по urlTemplate (из matchDetails)."""
        params = {"matchId": match_id, "language": "ru", "urlTemplate": url_template}
        if languages:
            params["languages"] = ",".join(languages)
        return await self.get(f"{API}/matchInsights", params, kind="insights")

    async def round(self, match_id, league_id) -> dict:
        """Все матчи тура со статусами и счётом (тот же запрос рисует блок тура на fotmob.com)."""
        return await self.get(f"{BASE}/leagueDataForMatch", {"matchId": match_id, "leagueId": league_id}, kind="round")

    async def vote(self, match_id) -> dict:
        """Голоса пользователей FotMob «Кто победит?» — только чтение."""
        return await self.get(f"{BASE}/vote", {"matchId": match_id}, kind="vote")

    async def ltc(self, match_id, teams: list[str], lang: str = "en") -> dict | None:
        """Текстовая трансляция Opta. Нет файла — FotMob отвечает null."""
        return await self.get(f"{BASE}/ltc", {"ltcUrl": LTC_URL.format(id=match_id, lang=lang),
                                               "teams": json.dumps(teams, ensure_ascii=False)}, kind="ltc")

    async def player(self, player_id) -> dict:
        raw = await self.get(f"{BASE}/playerData", {"id": player_id}, kind="player")
        # на несуществующий id FotMob отвечает 200 без игрока — это «нет такого», а не поломка
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("name"):
            raise NotFound(f"playerData {player_id}: пустой ответ")
        return raw


class FotMobExtra(FotMob):
    """Тот же клиент FotMob (User-Agent, таймауты, breaker, счётчики) для редких запросов экрана матча:
    факты, тур, голоса, трансляция. Свой breaker — если с сервера эти эндпоинты не отвечают,
    основной matchDetails не страдает. Выключается вместе с «fotmob» или отдельно: DISABLED_SOURCES=fotmob_extra;
    отдельная фича — fotmob_insights / fotmob_round / fotmob_vote / fotmob_ltc."""
    name = "fotmob_extra"

    def disabled(self) -> bool:
        return super().disabled() or "fotmob" in config.disabled_sources()

    @staticmethod
    def feature_disabled(kind: str) -> bool:
        return f"fotmob_{kind}" in config.disabled_sources()


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
        lt = st.get("liveTime") or {}
        # перерыв FotMob отдаёт в liveTime (short «HT», shortKey «halftime_short»), а не в reason
        if reason.upper() == "HT" or str(lt.get("short") or "").upper() == "HT" or lt.get("shortKey") == "halftime_short":
            return status("halftime", 45, label="HT")
        mi, add = _minute(lt)
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
    # группа xG, «Единоборства» и прочее, что раньше отбрасывали
    "big_chance_missed_title": "big_chances_missed", "expected_goals_open_play": "xg_open_play",
    "expected_goals_set_play": "xg_set_play", "expected_goals_non_penalty": "xg_non_penalty",
    "own_half_passes": "passes_own_half", "opposition_half_passes": "passes_opp_half",
    "player_throws": "throws", "shot_blocks": "blocks", "duel_won": "duels_won",
    "ground_duels_won": "ground_duels_won", "aerials_won": "aerials_won", "dribbles_succeeded": "dribbles",
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


_ZONE_PERIODS = {"total": "all", "firstHalf": "first_half", "secondHalf": "second_half"}


def _zones(raw: dict | None) -> dict | None:
    """content.attackingZones: доля атак по флангам (%), {период: {home: {left, center, right}, away: ...}}."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for src, our in _ZONE_PERIODS.items():
        per = {}
        for side in ("home", "away"):
            z = ((raw.get(side) or {}).get(src)) or {}
            vals = {k: num(z.get(k)) for k in ("left", "center", "right")}
            if all(isinstance(v, (int, float)) for v in vals.values()) and sum(vals.values()) > 0:
                per[side] = vals
        if len(per) == 2:
            out[our] = per
    return out if out.get("all") else None


def _weather(w: dict | None) -> dict | None:
    """content.weather: °C, ключ описания (weather_condition_*), влажность, облачность, осадки.
    Ветер не берём: единицы в ответе не указаны."""
    if not isinstance(w, dict) or num(w.get("temperature")) is None:
        return None
    return {"temp": num(w.get("temperature")), "key": w.get("localizedKey") or None,
            "text": w.get("description") or w.get("defaultTitle") or None,
            "humidity": num(w.get("relativeHumidity")), "cloud": num(w.get("cloudCover")),
            "precip": num(w.get("precipitation")), "icon": num(w.get("iconCode")),
            "at": iso_utc(w.get("lastUpdated")) if w.get("lastUpdated") else None}


_LEVEL = {"above": "above", "average": "average", "below": "below"}


def _ref_scale(s: dict | None) -> dict | None:
    """Шкала судьи «ЖК / матч», «Фолы / матч»: значение, среднее по лиге, метка и позиции на шкале (FotMob)."""
    if not s or num(s.get("value")) is None:
        return None
    return {"per_match": num(s.get("value")), "avg": num(s.get("average")), "total": num(s.get("total")),
            "level": _LEVEL.get(str(s.get("averageType") or "").lower()),
            "fill": num(s.get("fillPercentage")), "avg_fill": num(s.get("averagePercentage"))}


def _referee_info(ref: dict) -> dict | None:
    """infoBox.Referee: id (фото — /img/player/<id>.png), матчи в лиге, ЖК и фолы за матч со средним по лиге."""
    rid = _int(ref.get("id"))
    stats = {s.get("type"): s for s in ref.get("stats") or [] if isinstance(s, dict)}
    if not rid and not stats:
        return None

    def total(k):
        return num((stats.get(k) or {}).get("value"))

    lid = _int(ref.get("leagueId"))
    return {"id": rid, "photo": img_player(rid), "matches": total("matches"),
            "league": {"id": lid, "name": ref.get("leagueName")} if lid or ref.get("leagueName") else None,
            "yellow": _ref_scale(stats.get("yellowCards")), "fouls": _ref_scale(stats.get("fouls")),
            "red": total("redCards"), "pens": total("penalties")}


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
    m["venue"] = venue_ref(stadium.get("name"), stadium.get("city"), stadium.get("country"),
                           capacity=stadium.get("capacity"), surface=stadium.get("surface"))
    ref = info.get("Referee") or {}
    m["referee"] = ref.get("text") or None
    if m["referee"]:
        m["referee_country"] = country_ref(ref.get("countryCode"), ref.get("country"))
        m["referee_info"] = _referee_info(ref)
    m["weather"] = _weather(c.get("weather"))
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
    m["zones"] = _zones(c.get("attackingZones"))

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
                          "kickoff": iso_utc((f.get("date") or {}).get("utcTime")),
                          "opponent": _form_opponent(f)} for f in side]
                     for k, side in zip(("home", "away"), tf)}
    return finish_match(m, "fotmob")


def match_meta(raw: dict) -> dict:
    """Что нужно сборщику для редких запросов по матчу (факты, тур, трансляция) — из того же matchDetails.
    Пишется в ctx:fm:<id>; в ответ API не попадает."""
    g = raw.get("general") or {}
    c = raw.get("content") or {}
    ic = (c.get("matchFacts") or {}).get("matchInsightsConfig") or {}
    lt = c.get("liveticker") or {}
    langs = [x.split("_")[0] for x in str(lt.get("langs") or "").split(",") if x]
    parent = _int(g.get("parentLeagueId")) or _int(g.get("leagueId"))
    rnd = g.get("leagueRoundName") or g.get("matchRound") or None
    return {
        "league_id": _int(g.get("leagueId")) or parent,
        "parent_league_id": parent,
        "round": str(rnd) if rnd not in (None, "") else None,
        "round_key": round_key(parent, rnd),
        "insights_url": ic.get("urlTemplate") or None,
        "insights_languages": ic.get("languages") or None,
        "ltc_langs": langs,
        "ltc_teams": [t for t in (lt.get("teams") or []) if isinstance(t, str)],
        "home_id": _int((g.get("homeTeam") or {}).get("id")),
        "away_id": _int((g.get("awayTeam") or {}).get("id")),
    }


def round_key(league_id, rnd) -> str | None:
    """Ключ снимка тура: round:<турнир>:<тур>."""
    if not league_id or rnd in (None, ""):
        return None
    return f"round:{league_id}:{str(rnd).strip()}"


# ---------- «Интересные факты», тур, голоса, трансляция ----------

# предохранитель: «главный факт» FotMob называет bettingInsight; по сути это статистика,
# но строку со ставочными словами не показываем никогда
_BETTING_RE = re.compile(r"коэфф|ставк|букмекер|\bodds\b|\bbet", re.I)
INSIGHTS_PER_TEAM = 5


def normalize_insights(raw, home_id=None, away_id=None) -> dict | None:
    """/api/matchInsights?language=ru → {lang, main, teams: [{team_id, items}]} (хозяева первыми)."""
    if not isinstance(raw, dict):
        return None
    ti = raw.get("teamInsights") or {}
    if not isinstance(ti, dict):
        ti = {}
    order = [str(x) for x in (home_id, away_id) if x] + [str(k) for k in ti]
    teams = []
    for tid in dict.fromkeys(order):
        items = [t.strip() for t in ti.get(tid) or [] if isinstance(t, str) and t.strip()
                 and not _BETTING_RE.search(t)]
        if items:
            teams.append({"team_id": _int(tid), "items": items[:INSIGHTS_PER_TEAM]})
    main = raw.get("bettingInsight")
    main = main.strip() if isinstance(main, str) and main.strip() and not _BETTING_RE.search(main) else None
    if not teams and not main:
        return None
    return {"lang": "ru", "main": main, "teams": teams}


def _round_row(x: dict) -> dict:
    st = x.get("status") or x.get("liveStatus") or {}
    s = _status(st)
    home, away = x.get("home") or {}, x.get("away") or {}
    started = s["state"] not in ("scheduled", "postponed", "cancelled")
    hid, aid = _int(home.get("id")), _int(away.get("id"))
    return {
        "id": _int(x.get("id")),
        "kickoff": iso_utc(x.get("utcTime") or st.get("utcTime")),
        "home": {"id": hid, "name": home.get("shortName") or home.get("name"),
                 "score": x.get("homeScore") if started else None, "logo": img_team(hid)},
        "away": {"id": aid, "name": away.get("shortName") or away.get("name"),
                 "score": x.get("awayScore") if started else None, "logo": img_team(aid)},
        "status": s,
        "is_ours": config.TEAM_ID in (hid, aid),
    }


def normalize_round(raw, league_id=None) -> dict | None:
    """/api/data/leagueDataForMatch → матчи тура по времени начала. Нет matchesInRound (плей-офф) — None."""
    if not isinstance(raw, dict):
        return None
    src = [x for x in raw.get("matchesInRound") or [] if isinstance(x, dict) and x.get("id")]
    rows = [_round_row(x) for x in src]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["kickoff"] or "", r["id"] or 0))
    rnd = raw.get("currentRound") or next((x.get("roundName") for x in src if x.get("roundName")), None)
    return {"league": {"id": _int(league_id), "name": raw.get("leagueName"), "logo": img_league(league_id)},
            "round": str(rnd) if rnd not in (None, "") else None, "season": raw.get("seasonName"),
            "matches": rows,
            "live": sum(1 for r in rows if r["status"]["live"]),
            "finished": sum(1 for r in rows if r["status"]["finished"])}


def normalize_vote(raw) -> dict | None:
    """/api/data/vote → только исход 1/X/2 (bts / ou / dc — ставочные рынки, не берём)."""
    if not isinstance(raw, dict):
        return None
    v = next((x.get("Votes") for x in raw.get("Votes") or [] if isinstance(x, dict) and x.get("Name") == "1x2"), None)
    if not isinstance(v, list) or len(v) != 3 or not all(isinstance(n, int) and n >= 0 for n in v) or not sum(v):
        return None
    return {"home": v[0], "draw": v[1], "away": v[2], "total": sum(v)}


_LTC_TYPES = {"G": "goal", "OG": "own_goal", "AS": "assist", "YC": "yellow", "Y2C": "second_yellow", "RC": "red",
              "SI": "sub", "var": "var", "highlight": "chance", "comment": "comment", "team news": "team_news",
              "half_time summary": "summary", "full_time summary": "summary", "PM": "penalty_missed",
              "PS": "penalty_saved", "PSG": "penalty_goal"}
_LTC_NO_SIDE = {"comment", "chance", "team_news", "summary"}
LTC_LIMIT = 400


def normalize_ltc(raw) -> dict | None:
    """/api/data/ltc → записи трансляции (новые первыми, как у FotMob): минута, тип, текст, игроки."""
    if not isinstance(raw, dict):
        return None
    items = []
    for e in raw.get("events") or []:
        if not isinstance(e, dict):
            continue
        text = str(e.get("text") or "").strip()
        if not text:
            continue
        t = e.get("time") if isinstance(e.get("time"), dict) else {}
        added = re.sub(r"\D", "", str(t.get("added") or ""))
        mi = e.get("elapsed") if isinstance(e.get("elapsed"), int) and e["elapsed"] >= 0 else None
        if mi is None and t:
            mi = _int(re.sub(r"\D", "", str(t.get("main") or "")))
        ty = _LTC_TYPES.get(e.get("type"), "comment")
        items.append({
            "id": str(e.get("messageId") or e.get("optaEventId") or len(items)),
            "minute": mi, "added": int(added) if added else None,
            "type": ty,
            "side": e.get("teamEvent") if ty not in _LTC_NO_SIDE and e.get("teamEvent") in ("home", "away") else None,
            "text": text[:2000],
            "players": [{"id": _int(p.get("id")), "name": p.get("name"), "photo": img_player(p.get("id"))}
                        for p in e.get("players") or [] if isinstance(p, dict) and p.get("name")][:2],
        })
        if len(items) >= LTC_LIMIT:
            break
    if not items:
        return None
    return {"lang": raw.get("lang") or "en", "items": items,
            "updated": iso_utc(raw.get("lastUpdated")) if raw.get("lastUpdated") else None}


def _form_opponent(f: dict) -> dict | None:
    """Соперник в строке формы: та из команд home/away, что не isOurTeam (id FotMob → эмблема)."""
    for k in ("home", "away"):
        t = f.get(k) or {}
        if t and not t.get("isOurTeam") and (t.get("id") or t.get("name")):
            return {"id": _int(t.get("id")), "name": t.get("name")}
    return None


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
        "venue": venue_ref(venue.get("name"), venue.get("city"), venue.get("country")),
        "coach": coach,
        "squad": squad,
        "injuries": list(injuries.values()),
        "leaders": {"goals": tops("byGoals"), "assists": tops("byAssists"), "rating": tops("byRating")},
        "transfers": {"in": [_transfer(t) for t in tr.get("Players in") or []],
                      "out": [_transfer(t) for t in tr.get("Players out") or []]},
        "source": "fotmob",
        "available": ["squad", "player_photos", "injuries", "leaders", "transfers", "coach"],
    }


# ---------- игрок ----------

RECENT_LIMIT = 10
_FOOT = {"right": "right", "left": "left", "both": "both"}


def _date(v) -> str | None:
    """'2029-06-30T00:00:00.000Z' / {'utcTime': ...} → '2029-06-30'."""
    if isinstance(v, dict):
        v = v.get("utcTime") or v.get("dateValue")
    return str(v)[:10] if v and re.match(r"\d{4}-\d{2}-\d{2}", str(v)) else None


def _season_window(name: str | None) -> tuple[str, str] | None:
    """'2026/2027' → июль 2026 — июнь 2027; '2025' (КЧМ, ЧМ) → весь 2025 год."""
    m = re.fullmatch(r"(\d{4})/(\d{4})", str(name or "").strip())
    if m:
        return f"{m.group(1)}-07-01", f"{m.group(2)}-06-30T23:59:59Z"
    m = re.fullmatch(r"(\d{4})", str(name or "").strip())
    if m:
        return f"{m.group(1)}-01-01", f"{m.group(1)}-12-31T23:59:59Z"
    return None


def _rating(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("rating") if "rating" in v else v.get("num")
    x = num(v)
    return round(float(x), 2) if x else None


def _team_ref(tid, name) -> dict | None:
    if not name and not tid:
        return None
    return {"id": _int(tid), "name": name, "logo": img_team(tid)}


def _recent_row(m: dict) -> dict:
    home = bool(m.get("isHomeTeam"))
    hs, as_ = m.get("homeScore"), m.get("awayScore")
    ours, theirs = (hs, as_) if home else (as_, hs)
    res = None
    if ours is not None and theirs is not None:
        res = "W" if ours > theirs else "L" if ours < theirs else "D"
    lid = m.get("leagueId")
    return {
        "match_id": _int(m.get("id")),
        "kickoff": iso_utc((m.get("matchDate") or {}).get("utcTime")),
        "tournament": {"id": lid, "name": m.get("leagueName"), "logo": img_league(lid)},
        "team": _team_ref(m.get("teamId"), m.get("teamName")),
        "opponent": _team_ref(m.get("opponentTeamId"), m.get("opponentTeamName")),
        "home": home,
        "score": [hs, as_],
        "result": res,
        "conceded": theirs,
        "played": bool(m.get("playedInMatch")),
        "bench": bool(m.get("onBench")),
        "minutes": m.get("minutesPlayed"),
        "goals": m.get("goals") or 0, "assists": m.get("assists") or 0,
        "yellow": m.get("yellowCards") or 0, "red": m.get("redCards") or 0,
        "rating": _rating(m.get("ratingProps")),
        "potm": bool(m.get("playerOfTheMatch")),
    }


def _main_league_stats(raw: dict) -> dict:
    ml = raw.get("mainLeague") or {}
    out = {s.get("localizedTitleId"): s.get("value") for s in ml.get("stats") or []}
    deep = {}
    for g in ((raw.get("firstSeasonStats") or {}).get("statsSection") or {}).get("items") or []:
        for s in g.get("items") or []:
            deep.setdefault(s.get("localizedTitleId"), s.get("statValue"))
    return {"league_id": ml.get("leagueId"), "season": ml.get("season"), "stats": out, "deep": deep}


def _season(raw: dict, recent_all: list[dict], keeper: bool) -> dict | None:
    """Сезон клуба по турнирам. Матчи, голы, передачи и оценку даёт карьера FotMob (по каждому турниру);
    минуты и карточки — сумма по последним матчам, если они покрывают турнир целиком;
    основную лигу перекрывает блок mainLeague (там всё точно, у вратаря — сухие матчи)."""
    senior = (((raw.get("careerHistory") or {}).get("careerItems") or {}).get("senior") or {})
    entries = senior.get("seasonEntries") or []
    if not entries:
        return None
    e = entries[0]
    team_id = _int(e.get("teamId"))
    ml = _main_league_stats(raw)
    rows = []
    for t in e.get("tournamentStats") or []:
        if t.get("isFriendly"):
            continue
        lid = _int(t.get("leagueId"))
        apps = _int(t.get("appearances")) or 0
        row = {"league": {"id": lid, "name": t.get("leagueName"), "logo": img_league(lid)},
               "matches": apps, "started": None, "minutes": None,
               "goals": _int(t.get("goals")) or 0, "assists": _int(t.get("assists")) or 0,
               "rating": _rating(t.get("rating")), "yellow": None, "red": None,
               "clean_sheets": None, "conceded": None, "saves": None}
        win = _season_window(t.get("seasonName") or e.get("seasonName"))
        played = [m for m in recent_all if m["played"] and m["tournament"]["id"] == lid
                  and (m["team"] or {}).get("id") == team_id and win and m["kickoff"]
                  and win[0] <= m["kickoff"] <= win[1]]
        if apps and len(played) == apps:  # последние матчи покрывают турнир — суммы честные
            row["minutes"] = sum(m["minutes"] or 0 for m in played)
            row["yellow"] = sum(m["yellow"] for m in played)
            row["red"] = sum(m["red"] for m in played)
            if keeper:
                row["clean_sheets"] = sum(1 for m in played if m["conceded"] == 0)
                row["conceded"] = sum(m["conceded"] or 0 for m in played)
        if lid == ml["league_id"] and ml["season"] == e.get("seasonName"):
            s, deep = ml["stats"], ml["deep"]
            for ours, theirs in (("matches", "matches_uppercase"), ("started", "started"),
                                 ("minutes", "minutes_played"), ("goals", "goals"), ("assists", "assists"),
                                 ("yellow", "yellow_cards"), ("red", "red_cards"),
                                 ("clean_sheets", "clean_sheet_title"), ("conceded", "goals_conceded")):
                if isinstance(s.get(theirs), (int, float)):
                    row[ours] = s[theirs]
            if isinstance(s.get("rating"), (int, float)) and s["rating"]:
                row["rating"] = round(float(s["rating"]), 2)
            if keeper and num(deep.get("saves")) is not None:
                row["saves"] = num(deep.get("saves"))
        rows.append(row)
    if not rows:
        return None

    def total(k):
        vals = [r[k] for r in rows]
        return sum(vals) if all(v is not None for v in vals) else None

    totals = {k: total(k) for k in ("matches", "minutes", "goals", "assists", "yellow", "red")}
    totals["rating"] = _rating(e.get("rating"))
    if keeper:
        totals["clean_sheets"] = total("clean_sheets")
        totals["conceded"] = total("conceded")
        totals["saves"] = next((r["saves"] for r in rows if r["saves"] is not None), None) if len(rows) == 1 else None
    return {"name": e.get("seasonName"), "team": _team_ref(team_id, e.get("team")), "totals": totals,
            "tournaments": rows}


def _career(entries: list) -> list:
    out = []
    for e in entries or []:
        apps = _int(e.get("appearances"))
        if apps is None and not e.get("active"):
            continue  # «возвращение из аренды» на пару дней — без матчей, не показываем
        tt = (e.get("transferType") or {})
        out.append({
            "team": _team_ref(e.get("teamId"), e.get("team")),
            "start": _date(e.get("startDate")), "end": _date(e.get("endDate")),
            "active": bool(e.get("active")),
            "loan": (tt.get("localizationKey") or tt.get("text") or "").replace(" ", "_").lower() == "on_loan",
            "apps": apps, "goals": _int(e.get("goals")), "assists": _int(e.get("assists")),
        })
    return out


def normalize_player(raw: dict, now: datetime | None = None) -> dict:
    pid = raw.get("id")
    p = empty_player(pid)
    p["name"] = raw.get("name")
    info = {(x.get("translationKey") or x.get("title")): x for x in raw.get("playerInformation") or []}

    def val(key, field="numberValue"):
        return ((info.get(key) or {}).get("value") or {}).get(field)

    p["number"] = _int(val("shirt"))
    p["height"] = _int(val("height_sentencecase"))
    foot = (val("preferred_foot", "key") or "").lower()
    p["foot"] = _FOOT.get(foot)
    p["value_eur"] = _int(val("transfer_value"))
    p["contract_until"] = _date(raw.get("contractEnd")) or _date(val("contract_end", "dateValue"))
    p["birth"] = _date(raw.get("birthDate"))
    p["age"] = age_on(p["birth"], now) or _int(val("age_sentencecase"))

    c = info.get("country_sentencecase") or {}
    code = c.get("countryCode") or ((c.get("icon") or {}).get("id"))
    if code or (c.get("value") or {}).get("fallback"):
        p["country"] = {"code": code, "name": (c.get("value") or {}).get("fallback"), "flag": img_flag(code),
                        "team_id": _int(c.get("nationalTeamId"))}

    pt = raw.get("primaryTeam") or {}
    if pt.get("teamId") or pt.get("teamName"):
        p["team"] = {**_team_ref(pt.get("teamId"), pt.get("teamName")), "on_loan": bool(pt.get("onLoan"))}

    pos = (raw.get("positionDescription") or {}).get("positions") or []
    pos = sorted(pos, key=lambda x: (not x.get("isMainPosition"), -(x.get("occurences") or 0)))
    codes = [((x.get("strPosShort") or {}).get("label") or "").upper() for x in pos]
    p["positions"] = [c for c in dict.fromkeys(codes) if c]
    p["position"] = p["positions"][0] if p["positions"] else None
    p["role"] = ROLE_BY_POS.get(p["position"] or "")
    if raw.get("isCoach"):
        p["role"] = "COACH"

    inj = raw.get("injuryInformation") or None
    if isinstance(inj, dict) and (inj.get("name") or inj.get("expectedReturn")):
        er = inj.get("expectedReturn") or {}
        p["status"] = {"type": "suspension" if "suspen" in (inj.get("key") or inj.get("name") or "").lower()
                       else "injury",
                       "name": inj.get("name"),
                       "expected_return": er.get("expectedReturnFallback") if isinstance(er, dict) else er,
                       "updated": _date(inj.get("lastUpdated"))}

    recent_all = sorted((_recent_row(m) for m in raw.get("recentMatches") or []),
                        key=lambda r: r["kickoff"] or "", reverse=True)
    p["recent"] = [r for r in recent_all if r["played"]][:RECENT_LIMIT]
    p["season"] = _season(raw, recent_all, keeper=p["role"] == "GK")

    ci = (raw.get("careerHistory") or {}).get("careerItems") or {}
    p["career"] = _career((ci.get("senior") or {}).get("teamEntries"))
    p["national"] = _career((ci.get("national team") or {}).get("teamEntries"))
    return finish_player(p, "fotmob")
