"""LiveScore — последний резерв: счёт, голы с ассистами, карточки, замены, составы
(с позициями на поле по схеме), командная статистика и удары без xG по ударам.

Удобная особенность: scoreboard отдаёт Pids — id матча и команд у других провайдеров,
в т.ч. "1" — FotMob. Это наш мост для таблицы соответствий.

Коды инцидентов (IT) сверены на матче Рома–Реал: 36 гол, 63 ассист, 43 жёлтая,
4/5 — замена (ушёл/вышел). Остальные (37, 38, 39, 44, 45) — по общепринятой схеме
LiveScore, на реальных данных не проверены.
"""
import re

from .. import config
from ..model import (_LINE_X, empty_match, event, finish_match, img_league, img_team, iso_utc,
                     lineup_player, person, resolve_player, stat_list, status)
from .base import HttpxSource

BASE = "https://prod-public-api.livescore.com/v1/api/app"

IT_GOAL, IT_PEN_GOAL, IT_PEN_MISS, IT_OWN_GOAL = 36, 37, 38, 39
IT_YELLOW, IT_SECOND_YELLOW, IT_RED = 43, 44, 45
IT_ASSIST = 63
IT_SUB_OUT, IT_SUB_IN = 4, 5


class LiveScore(HttpxSource):
    name = "livescore"

    async def by_date(self, yyyymmdd: str) -> dict:
        return await self.get(f"{BASE}/date/soccer/{yyyymmdd}/0", {"MD": "1"}, kind="date")

    async def part(self, name: str, eid) -> dict:
        return await self.get(f"{BASE}/{name}/soccer/{eid}", {"MD": "1"}, kind=name)


_MIN = re.compile(r"(\d+)\s*(?:\+\s*(\d+))?")


def _status(sb: dict) -> dict:
    eps = str(sb.get("Eps") or "").strip()
    up = eps.upper().rstrip(".")
    if up in ("FT", "AET", "AP", "FT_PEN", "AWARDED", "AWD"):
        return status("finished", label=eps)
    if up == "HT":
        return status("halftime", 45, label="HT")
    if up in ("NS", ""):
        return status("scheduled", label=eps or None)
    if up.startswith("POSTP"):
        return status("postponed", label=eps)
    if up.startswith("CANC"):
        return status("cancelled", label=eps)
    if up.startswith("ABAN") or up == "ABD":
        return status("abandoned", label=eps)
    m = _MIN.search(eps)
    if m:
        return status("live", int(m.group(1)), int(m.group(2)) if m.group(2) else None, label=eps)
    if up in ("BREAK", "ET", "PEN", "AW"):
        return status("live", None, label=eps)
    return status("scheduled", label=eps)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fotmob_ids(sb: dict) -> dict:
    """Pids провайдера "1" = FotMob: матч и обе команды."""
    def team(t):
        return _int(((((t or [{}])[0]).get("Pids") or {}).get("1") or [None])[0])
    return {"match": _int((sb.get("Pids") or {}).get("1")), "home": team(sb.get("T1")), "away": team(sb.get("T2")),
            "sofa_home": _int(((((sb.get("T1") or [{}])[0]).get("Pids") or {}).get("6") or [None])[0]),
            "sofa_away": _int(((((sb.get("T2") or [{}])[0]).get("Pids") or {}).get("6") or [None])[0])}


def _name(i: dict) -> str | None:
    return i.get("Pn") or " ".join(x for x in (i.get("Fn"), i.get("Ln")) if x) or i.get("Snm")


def normalize_match(b: dict, ctx: dict | None = None) -> dict:
    """b = {"scoreboard": ..., "incidents": ..., "lineups": ..., "statistics": ...}"""
    ctx = ctx or {}
    sb = b.get("scoreboard") or {}
    ids = fotmob_ids(sb)
    m = empty_match()
    eid = sb.get("Eid")
    fm_id = ctx.get("match_id") or ids["match"]
    m["id"] = fm_id or (f"livescore:{eid}" if eid else None)
    m["ids"].update(fotmob=fm_id, livescore=eid)
    m["kickoff"] = iso_utc(str(sb.get("Esd"))) if sb.get("Esd") else None
    m["status"] = _status(sb)
    stg = sb.get("Stg") or {}
    lid = {"Champions League": 42, "LaLiga": 87, "Copa del Rey": 138, "Super Cup": 139,
           "Supercopa de Espana": 139}.get(stg.get("CompN") or stg.get("Cnm"))
    m["tournament"] = {"id": lid, "name": stg.get("CompN") or stg.get("Cnm"), "round": stg.get("Snm"),
                       "logo": img_league(lid)}
    v = sb.get("Venue") or {}
    if v.get("Vnm"):
        m["venue"] = {"name": v.get("Vnm"), "city": v.get("Vcy")}
        m["attendance"] = v.get("Vsp")
    started = m["status"]["state"] not in ("scheduled", "postponed", "cancelled")
    for key, n, fm_team in (("home", "1", ids["home"]), ("away", "2", ids["away"])):
        t = (sb.get(f"T{n}") or [{}])[0]
        m[key].update(id=fm_team, name=t.get("Nm"), short=t.get("Abr"),
                      score=_int(sb.get(f"Tr{n}")) if started else None,
                      ht_score=_int(sb.get(f"Trh{n}")), logo=img_team(fm_team))

    def side_of(i):
        return "home" if i.get("Nm") == 1 else "away"

    def pers(i, side):
        return person(name=_name(i), fotmob_id=resolve_player(ctx, side, i.get("Pnum"), _name(i)))

    incs = (b.get("incidents") or {}).get("Incs") or {}
    for per in sorted(incs, key=lambda x: _int(x) or 0):
        for grp in incs[per]:
            items = grp.get("Incs") or [grp]
            side = side_of(grp)
            main = next((i for i in items if i.get("IT") in (IT_GOAL, IT_PEN_GOAL, IT_OWN_GOAL)), None)
            if main:
                ast = next((i for i in items if i.get("IT") == IT_ASSIST), None)
                m["events"].append(event(
                    "goal", grp.get("Min"), grp.get("MinEx"), side, player=pers(main, side),
                    assist=pers(ast, side) if ast else None, own_goal=main.get("IT") == IT_OWN_GOAL,
                    penalty=main.get("IT") == IT_PEN_GOAL, shootout=False, score=list(grp.get("Sc") or [])))
                continue
            for i in items:
                it = i.get("IT")
                if it in (IT_YELLOW, IT_SECOND_YELLOW, IT_RED):
                    card = {IT_YELLOW: "yellow", IT_SECOND_YELLOW: "second_yellow", IT_RED: "red"}[it]
                    m["events"].append(event("card", i.get("Min"), i.get("MinEx"), side_of(i), card=card,
                                             player=pers(i, side_of(i)), reason=None))
                elif it == IT_PEN_MISS:
                    m["events"].append(event("penalty_missed", i.get("Min"), i.get("MinEx"), side_of(i),
                                             player=pers(i, side_of(i))))

    lu = b.get("lineups") or {}
    subs_in, subs_out = {}, {}
    for per, lst in (lu.get("Subs") or {}).items():
        pairs = {}
        for i in lst:
            pairs.setdefault((i.get("Min"), i.get("Nm"), frozenset((i.get("ID"), i.get("IDo")))), []).append(i)
        for (mi, nm, _), items in pairs.items():
            pin = next((i for i in items if i.get("IT") == IT_SUB_IN), None)
            pout = next((i for i in items if i.get("IT") == IT_SUB_OUT), None)
            side = "home" if nm == 1 else "away"
            if pin:
                subs_in[pin.get("ID")] = mi
            if pout:
                subs_out[pout.get("ID")] = mi
            m["events"].append(event("sub", mi, (pin or pout or {}).get("MinEx"), side,
                                     player_in=pers(pin, side) if pin else None,
                                     player_out=pers(pout, side) if pout else None, injury=None))
    if m["home"]["ht_score"] is not None and m["status"]["state"] in ("finished", "live") and \
            (m["status"]["state"] == "finished" or (m["status"]["minute"] or 0) > 45):
        m["events"].append(event("period", 45, None, None, label="HT",
                                 score=[m["home"]["ht_score"], m["away"]["ht_score"]]))

    teams = lu.get("Lu") or []
    if len(teams) == 2 and all(t.get("Ps") for t in teams):
        m["lineups"] = {"confirmed": True}
        for t in teams:
            key = "home" if t.get("Tnb") == 1 else "away"
            fo = t.get("Fo") or []
            line_sizes = [1] + [int(x) for x in fo]
            n = len(fo)
            ys = [0.1] + ([round(0.29 + i * (0.58 / (n - 1)), 2) for i in range(n)] if n > 1 else [0.5])

            def xy(p):
                try:
                    ln, idx = (int(x) for x in str(p.get("Fp")).split(":"))
                    k = line_sizes[ln - 1]
                    return _LINE_X[k][idx - 1], ys[ln - 1]
                except (ValueError, IndexError, KeyError, TypeError):
                    return None, None

            def pl(p, starter):
                name = p.get("Snm") or " ".join(x for x in (p.get("Fn"), p.get("Ln")) if x)
                x, y = xy(p) if starter else (None, None)
                return lineup_player(name, p.get("Snu"),
                                     fotmob_id=resolve_player(ctx, key, p.get("Snu"), name),
                                     position={1: "GK", 2: "DF", 3: "MF", 4: "FW"}.get(p.get("Pos")),
                                     rating=None, x=x, y=y, captain=False,
                                     sub_in=subs_in.get(p.get("Pid")), sub_out=subs_out.get(p.get("Pid")),
                                     source_id=p.get("Pid"))

            starters = [p for p in t["Ps"] if p.get("Fp")]
            bench = [p for p in t["Ps"] if not p.get("Fp")]
            m["lineups"][key] = {
                "team_id": m[key]["id"], "formation": "-".join(str(x) for x in fo) or None, "rating": None,
                "coach": None, "starters": [pl(p, True) for p in starters], "subs": [pl(p, False) for p in bench],
                "unavailable": [],
            }

    st = b.get("statistics") or {}
    stat = {s.get("Tnb"): s for s in st.get("Stat") or []}
    if 1 in stat and 2 in stat:
        h, a = stat[1], stat[2]

        def tot(s):
            vals = [s.get(k) for k in ("Shon", "Shof", "Shbl")]
            return sum(v for v in vals if isinstance(v, (int, float))) if any(v is not None for v in vals) else None

        pairs = {"possession": (h.get("Pss"), a.get("Pss")), "xg": (h.get("Xg"), a.get("Xg")),
                 "shots_total": (tot(h), tot(a)), "shots_on_target": (h.get("Shon"), a.get("Shon")),
                 "shots_off_target": (h.get("Shof"), a.get("Shof")), "shots_blocked": (h.get("Shbl"), a.get("Shbl")),
                 "shots_woodwork": (h.get("Shwd"), a.get("Shwd")), "corners": (h.get("Cos"), a.get("Cos")),
                 "fouls": (h.get("Fls"), a.get("Fls")), "offsides": (h.get("Ofs"), a.get("Ofs")),
                 "yellow_cards": (h.get("Ycs"), a.get("Ycs")), "red_cards": (h.get("Rcs"), a.get("Rcs")),
                 "saves": (h.get("Gks"), a.get("Gks"))}
        m["stats"] = {"all": stat_list(pairs), "first_half": [], "second_half": []}

    # удары: ST 1 — в створ (сейв), 2 — мимо/заблокирован, 3 — гол (сверено с FotMob на Рома–Реал)
    st_map = {1: "saved", 2: "miss", 3: "goal"}
    lu_names = {}
    for t in teams:
        key = "home" if t.get("Tnb") == 1 else "away"
        for p in t.get("Ps") or []:
            lu_names[str(p.get("Pid"))] = (key, p.get("Snm") or " ".join(x for x in (p.get("Fn"), p.get("Ln")) if x),
                                           p.get("Snu"))
    for per, lst in (st.get("shotsMap") or {}).items():
        for grp in lst:
            side = "home" if str(grp.get("Tnb")) == "1" else "away"
            for s in grp.get("shots") or []:
                _, nm, num = lu_names.get(str(s.get("Aid")), (side, None, None))
                m["shots"].append({
                    "x": float(s["x"]) if s.get("x") else None, "y": float(s["y"]) if s.get("y") else None,
                    "minute": None, "added": None, "side": side,
                    "player": person(name=nm, fotmob_id=resolve_player(ctx, side, num, nm)) if nm else None,
                    "outcome": st_map.get(s.get("ST"), "miss"), "own_goal": False, "xg": None, "xgot": None,
                    "situation": None, "body": None, "period": {"1": "FirstHalf", "2": "SecondHalf"}.get(per, per),
                })
    return finish_match(m, "livescore")


def find_event(date_payload: dict, home: str | None, away: str | None, kickoff_iso: str | None):
    """(Eid, точно) матча в выдаче по дате. Точно = обе команды и час начала совпали."""
    from ..model import same_team
    loose = None
    for stg in date_payload.get("Stages") or []:
        for e in stg.get("Events") or []:
            t1 = ((e.get("T1") or [{}])[0]).get("Nm")
            t2 = ((e.get("T2") or [{}])[0]).get("Nm")
            if same_team(t1, home) and same_team(t2, away):
                if kickoff_iso and e.get("Esd") and iso_utc(str(e["Esd"]))[:13] != kickoff_iso[:13]:
                    loose = loose or e.get("Eid")
                    continue
                return e.get("Eid"), True
    return loose, False
