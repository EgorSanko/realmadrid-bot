"""Мадридиста — API. Только читает снимки сборщика из SQLite; во внешние источники не ходит.

Каждый ответ несёт `source` (откуда снимок), `updated_at` (когда получен), `age_s` и `stale`.
Если все источники упали, сборщик снимок не трогает — здесь отдаётся последний удачный
с его возрастом и кодом 200.
"""
import os
import re
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import auth_api, config, store, visits
from .model import result_for, ts
from .games import api as games_api
from .predictions import api as predict_api
from .predictions.snapshot_provider import SnapshotProvider
from .sources import article, fotmob, media
from .stream import router as stream_router

VERSION = "0.2.0"
# git sha сборки: deploy.sh передаёт GIT_SHA в docker compose build → ARG → ENV BUILD_SHA
BUILD_SHA = os.environ.get("BUILD_SHA") or None
HEARTBEAT_OK_S = 300  # сборщик пишет сердцебиение раз в 5 с; старше 5 мин — он стоит (watchdog перезапустит)

app = FastAPI(title="Мадридиста API", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(stream_router)
predict_api.install(app)  # /api/predict/* — этап 10
auth_api.install(app)     # /api/auth/* — вход через Telegram и сессия
games_api.install(app)    # /api/games/* — викторина и пенальти (отдельный рейтинг, без очков прогнозов)
visits.install(app)       # /api/visit и /api/admin/stats — счётчик людей без входа (хеш id устройства)

# прогнозы читают матчи из снимков сборщика (rm.sqlite3); тесты и проверки подставляют свой сервис сами
if predict_api._service is None:
    predict_api.configure(provider=SnapshotProvider())

# через сколько секунд снимок считается устаревшим (≈ 3 пропущенных цикла сборщика)
STALE_AFTER = {"fixtures": 3 * config.TEAM_INTERVAL, "tables": 3 * config.TEAM_INTERVAL,
               "team": 3 * config.TEAM_INTERVAL, "match_live": 6 * config.LIVE_INTERVAL,
               "match_idle": 2 * config.IDLE_MATCH_INTERVAL + 60,
               "news": 3 * config.NEWS_INTERVAL, "videos": 3 * config.VIDEO_INTERVAL}


def _db():
    return store.connect()


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _meta(snap: dict, stale_after: float) -> dict:
    age = time.time() - snap["fetched_at"]
    return {"source": snap["source"], "updated_at": _iso(snap["fetched_at"]), "age_s": round(age, 1),
            "stale": age > stale_after}


def _resp(body: dict, max_age: int, status_code: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status_code,
                        headers={"Cache-Control": f"public, max-age={max_age}" if max_age else "no-store"})


def _no_data(what: str) -> JSONResponse:
    # снимков ещё нет (холодный старт сборщика) — честно 503, без падения
    return _resp({"error": "no_data", "detail": f"{what}: сборщик ещё не получил данные", "available": []}, 0, 503)


def _heartbeat_age() -> float | None:
    try:
        with open(config.HEARTBEAT_FILE) as f:
            return round(time.time() - float(f.read().strip()), 1)
    except (OSError, ValueError):
        return None


_COUNTS: dict = {"at": 0.0, "value": None}
COUNTS_TTL = 60  # health дёргают healthcheck (30 с) и мониторинг — базу прогнозов считаем не чаще раза в минуту


def _counts() -> dict | None:
    """Сколько пользователей и прогнозов — только числа, без персональных данных."""
    now = time.monotonic()
    if _COUNTS["value"] is not None and now - _COUNTS["at"] < COUNTS_TTL:
        return _COUNTS["value"]
    svc = predict_api._service
    if svc is None:
        return None
    try:
        with svc.conn() as c:
            value = {"users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                     "predictions": c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]}
    except Exception:  # health не должен падать из-за базы прогнозов
        return None
    _COUNTS.update(at=now, value=value)
    return value


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health() -> JSONResponse:  # sync: чтение базы — в пуле потоков, не в цикле событий
    """Живость API (всегда 200, пока процесс отвечает) + сведения для мониторинга: сборка,
    возраст сердцебиения сборщика, число пользователей и прогнозов."""
    hb = _heartbeat_age()
    return _resp({"status": "ok", "version": VERSION, "build": BUILD_SHA,
                  "time": datetime.now(timezone.utc).isoformat(),
                  "collector": {"heartbeat_age_s": hb, "ok": hb is not None and hb < HEARTBEAT_OK_S},
                  "counts": _counts()}, 0)


# ---------- главная ----------

def _match_overlay(conn, f: dict) -> tuple[dict, dict | None]:
    """Свежий статус/счёт/стадион из снимка матча поверх строки календаря."""
    snap = store.get(conn, f"match:{f['id']}")
    if not snap:
        return f, None
    m = snap["data"]
    f = dict(f)
    f["status"] = m["status"]
    f["home"] = {**f["home"], "score": m["home"]["score"]}
    f["away"] = {**f["away"], "score": m["away"]["score"]}
    return f, {"venue": m.get("venue"), "source": snap["source"], "updated_at": _iso(snap["fetched_at"])}


def _brief(f: dict, extra: dict | None) -> dict:
    return {
        "id": f["id"], "kickoff": f["kickoff"], "tournament": f["tournament"],
        "home": f["home"], "away": f["away"], "status": f["status"], "is_home": f.get("is_home"),
        "result": f.get("result"), "venue": (extra or {}).get("venue"),
    }


@app.get("/api/home")
def home() -> JSONResponse:
    conn = _db()
    try:
        fx = store.get(conn, "fixtures")
        if not fx:
            return _no_data("fixtures")
        tb = store.get(conn, "tables")
        now = time.time()
        fixtures = fx["data"]
        live = [f for f in fixtures if f["status"]["live"]]
        upcoming = [f for f in fixtures if not f["status"]["finished"]
                    and f["status"]["state"] not in ("cancelled", "postponed")
                    and (ts(f["kickoff"]) or 0) > now - 4 * 3600]
        done = [f for f in fixtures if f["status"]["finished"]]
        # календарь обновляется раз в 12 мин: матч, который по лайв-снимку уже завершён, — «последний»,
        # а «следующим» становится следующий за ним (иначе до обновления висел бы как live со старой минутой)
        picked: dict[str, tuple[dict, dict | None]] = {}
        for f in [*live, *[f for f in upcoming if f not in live]]:
            f2, extra = _match_overlay(conn, f)
            if not f2["status"]["finished"]:
                picked["next"] = (f2, extra)
                break
            if "last" not in picked:
                f2["result"] = f2.get("result") or result_for(config.TEAM_ID, f2["home"].get("id"),
                                                               f2["home"].get("score"), f2["away"].get("score"))
                picked["last"] = (f2, extra)
        if "last" not in picked and done:
            picked["last"] = _match_overlay(conn, done[-1])
        sources = {"fixtures": _meta(fx, STALE_AFTER["fixtures"])}
        body = {"next": None, "last": None}
        for key in ("next", "last"):
            if key in picked:
                f2, extra = picked[key]
                body[key] = _brief(f2, extra)
                if extra:
                    sources[f"{key}_match"] = {"source": extra["source"], "updated_at": extra["updated_at"]}
        form = [{"id": f["id"], "result": f["result"], "kickoff": f["kickoff"],
                 "opponent": f["away"] if f.get("is_home") else f["home"],
                 "score": f"{f['home']['score']}-{f['away']['score']}", "tournament": f["tournament"]["name"]}
                for f in done[-5:]][::-1]
        laliga = None
        if tb:
            sources["tables"] = _meta(tb, STALE_AFTER["tables"])
            t = next((t for t in tb["data"] if t["league"]["id"] == 87), None)
            row = next((r for r in (t or {}).get("rows", []) if r["is_us"]), None)
            if row:
                laliga = {"league": t["league"], "pos": row["pos"], "pts": row["pts"], "played": row["played"],
                          "w": row["w"], "d": row["d"], "l": row["l"], "gd": row["gd"],
                          "leader_pts": t["rows"][0]["pts"] if t["rows"] else None}
        body.update(form=form, laliga=laliga, round=None)
        # идёт матч Реала — компактная лента его тура (снимок round:<турнир>:<тур> сборщика)
        nxt = picked["next"][0] if "next" in picked else None
        if nxt and body["next"]["status"]["live"] and nxt["tournament"].get("id") in config.ROUND_LEAGUES:
            msnap = store.get(conn, f"match:{nxt['id']}")
            rk = _round_snapshot_key(conn, str(nxt["id"]), (msnap or {}).get("data") or nxt)
            rs = store.get(conn, rk) if rk else None
            if rs and rs["data"].get("matches"):
                body["round"] = {k: rs["data"].get(k) for k in ("league", "round", "matches", "live", "finished")}
        avail = [k for k in ("next", "last", "form", "laliga", "round") if body.get(k)]
        if body["next"] and body["next"].get("venue"):
            avail.append("venue")
        live_now = bool(body["next"] and body["next"]["status"]["live"])
        return _resp({**_meta(fx, STALE_AFTER["fixtures"]), "sources": sources, "available": avail, **body},
                      5 if live_now else 30)
    finally:
        conn.close()


# ---------- матч ----------

_POLL_CACHE: dict[str, tuple[float, dict | None]] = {}
POLL_TTL = 60  # агрегат прогнозов считаем не чаще раза в минуту на матч (/api/match опрашивают раз в 10 с)


def _our_outcomes(match_id: str) -> dict | None:
    """Исходы 1/X/2 из прогнозов счёта (база прогнозов). Нет сервиса или база недоступна — None."""
    now = time.monotonic()
    hit = _POLL_CACHE.get(match_id)
    if hit and now - hit[0] < POLL_TTL:
        return hit[1]
    svc = predict_api._service
    value = None
    if svc is not None:
        try:
            value = svc.outcome_counts(match_id)
        except Exception:  # «Кто победит?» не должен ронять экран матча
            value = None
    if len(_POLL_CACHE) > 500:
        _POLL_CACHE.clear()
    _POLL_CACHE[match_id] = (now, value)
    return value


def _round_snapshot_key(conn, match_id: str, m: dict) -> str | None:
    ctx = store.get(conn, f"ctx:fm:{match_id}")
    if ctx and ctx["data"].get("round_key"):
        return ctx["data"]["round_key"]
    t = m.get("tournament") or {}
    return fotmob.round_key(t.get("id"), t.get("round"))


def _match_extras(conn, match_id: str, m: dict) -> dict:
    """Факты, тур, «Кто победит?» и сводка трансляции — из отдельных снимков сборщика (в источники не ходим).
    Нет снимка — поле null, пункта в available нет: экран просто прячет блок."""
    out = {"insights": None, "round": None, "poll": None, "commentary": None}
    ins = store.get(conn, f"insights:{match_id}")
    if ins:
        out["insights"] = {**ins["data"], "updated_at": _iso(ins["fetched_at"])}
    if (m.get("tournament") or {}).get("id") in config.ROUND_LEAGUES:
        rk = _round_snapshot_key(conn, match_id, m)
        rs = store.get(conn, rk) if rk else None
        if rs and rs["data"].get("matches"):
            out["round"] = {**{k: v for k, v in rs["data"].items() if k != "match_ids"},
                            "updated_at": _iso(rs["fetched_at"])}
    vote = store.get(conn, f"vote:{match_id}")
    ours = _our_outcomes(match_id)
    n = (ours or {}).get("total") or 0
    fm_votes = vote["data"] if vote and vote["data"].get("total") else None
    if fm_votes or n:
        out["poll"] = {"fotmob": fm_votes, "ours": ours if n >= config.POLL_MIN_PREDICTIONS else None,
                       "ours_count": n, "threshold": config.POLL_MIN_PREDICTIONS,
                       "updated_at": _iso(vote["fetched_at"]) if vote else None}
    ltc = store.get(conn, f"ltc:{match_id}")
    if ltc and ltc["data"].get("items"):
        out["commentary"] = {"count": len(ltc["data"]["items"]), "lang": ltc["data"].get("lang") or "en",
                             "updated_at": _iso(ltc["fetched_at"])}
    return out


@app.get("/api/match/{match_id}/commentary")
def match_commentary(match_id: str) -> JSONResponse:
    """Текстовая трансляция Opta (через FotMob), английский оригинал: записи новыми первыми."""
    conn = _db()
    try:
        snap = store.get(conn, f"ltc:{match_id}")
        if not snap or not snap["data"].get("items"):
            return _resp({"items": [], "lang": None, "attribution": None, "available": []}, 30)
        m = store.get(conn, f"match:{match_id}")
        live = bool(m and m["data"]["status"]["live"])
        meta = _meta(snap, 6 * config.LTC_INTERVAL if live else STALE_AFTER["match_idle"])
        return _resp({**meta, "lang": snap["data"].get("lang") or "en", "attribution": "Opta via FotMob",
                      "items": snap["data"]["items"], "available": ["commentary"]}, 15 if live else 120)
    finally:
        conn.close()


@app.get("/api/match/{match_id}")
def match(match_id: str) -> JSONResponse:
    conn = _db()
    try:
        snap = store.get(conn, f"match:{match_id}")
        if snap:
            m = snap["data"]
            live = m["status"]["live"]
            meta = _meta(snap, STALE_AFTER["match_live" if live else "match_idle"])
            m.pop("finished_seen_at", None)
            extras = _match_extras(conn, match_id, m)
            avail = list(m.get("available") or []) + [k for k, v in extras.items() if v]
            return _resp({**m, **extras, **meta, "available": avail},
                         5 if live else (60 if m["status"]["finished"] else 30))
        # матча нет в снимках: если он есть в календаре — отдаём заголовок и просим сборщика подтянуть
        fx = store.get(conn, "fixtures")
        f = next((f for f in (fx["data"] if fx else []) if str(f["id"]) == match_id), None)
        if not f:
            return _resp({"error": "not_found", "detail": "матча нет ни в снимках, ни в календаре"}, 30, 404)
        store.ask(conn, match_id)
        body = {**f, "events": [], "lineups": None, "stats": None, "shots": [], "momentum": [], "potm": None,
                "highlights": None, "h2h": None, "form": None, "venue": None, "weather": None, "referee_info": None,
                "zones": None, "insights": None, "round": None, "poll": None, "commentary": None,
                "available": [], "pending": True,
                **_meta(fx, STALE_AFTER["fixtures"])}
        return _resp(body, 5)
    finally:
        conn.close()


# ---------- календарь / таблицы / команда ----------

@app.get("/api/fixtures")
def fixtures() -> JSONResponse:
    conn = _db()
    try:
        fx = store.get(conn, "fixtures")
        if not fx:
            return _no_data("fixtures")
        counts = {}
        for f in fx["data"]:
            counts[f["tournament"]["name"]] = counts.get(f["tournament"]["name"], 0) + 1
        # календарь сборщик обновляет раз в 12 мин — матчу вокруг «сейчас» статус и счёт берём
        # из его лайв-снимка, иначе идущий матч в «Матчах» выглядит предстоящим
        now = time.time()
        matches = [_match_overlay(conn, f)[0] if abs((ts(f["kickoff"]) or 0) - now) <= 4 * 3600 else f
                   for f in fx["data"]]
        live = any(f["status"]["live"] for f in matches)
        return _resp({**_meta(fx, STALE_AFTER["fixtures"]), "tournaments": counts, "matches": matches},
                     5 if live else 60)
    finally:
        conn.close()


@app.get("/api/tables")
def tables() -> JSONResponse:
    conn = _db()
    try:
        tb = store.get(conn, "tables")
        if not tb:
            return _no_data("tables")
        return _resp({**_meta(tb, STALE_AFTER["tables"]), "tables": tb["data"]}, 60)
    finally:
        conn.close()


@app.get("/api/team")
def team() -> JSONResponse:
    conn = _db()
    try:
        t = store.get(conn, "team")
        if not t:
            return _no_data("team")
        return _resp({**t["data"], **_meta(t, STALE_AFTER["team"])}, 60)
    finally:
        conn.close()


# ---------- карточка игрока ----------

_PLAYER_ID = re.compile(r"[1-9]\d{0,9}")


def _squad_ids(conn) -> set[str]:
    t = store.get(conn, "team")
    return {str(p["id"]) for line in ((t or {}).get("data", {}).get("squad") or {}).values()
            for p in line if p.get("id")}


@app.get("/api/player/{player_id}")
def player(player_id: str) -> JSONResponse:
    """Снимок карточки игрока. Нет снимка — `pending: true` и заявка сборщику (клиент повторяет запрос);
    снимок старше срока (свои — 6 ч, чужие — 24 ч) — отдаём его и тоже просим обновить."""
    if not _PLAYER_ID.fullmatch(player_id):
        return _resp({"error": "not_found", "detail": "неверный id игрока", "available": []}, 60, 404)
    conn = _db()
    try:
        now = time.time()
        snap = store.get(conn, f"player:{player_id}")
        if snap:
            d = snap["data"]
            own = player_id in _squad_ids(conn) or (d.get("team") or {}).get("id") == config.TEAM_ID
            ttl = config.PLAYER_INTERVAL if own else config.PLAYER_FOREIGN_TTL
            if now - snap["fetched_at"] >= ttl:
                store.ask_player(conn, player_id)
            d.pop("fallback_errors", None)
            stale_after = 3 * config.PLAYER_INTERVAL if own else config.PLAYER_FOREIGN_TTL + 3600
            return _resp({**d, **_meta(snap, stale_after), "pending": False}, 300)
        fail = store.get(conn, f"player_fail:{player_id}")
        if fail and now - fail["fetched_at"] < config.PLAYER_FAIL_RETRY:
            if fail["data"].get("not_found"):
                return _resp({"error": "not_found", "detail": "такого игрока нет у источника", "available": []},
                             60, 404)
            return _resp({"error": "unavailable", "detail": "источники не ответили, попробуем позже",
                          "available": []}, 0, 503)
        if not store.ask_player(conn, player_id):
            return _resp({"error": "busy", "detail": "очередь сборщика переполнена", "available": []}, 0, 503)
        return _resp({"id": int(player_id), "pending": True, "available": [], "source": None,
                      "updated_at": None, "age_s": None, "stale": False}, 0)
    finally:
        conn.close()


# ---------- медиа: новости и видео ----------

def _limit(v: int | None, default: int, top: int) -> int:
    try:
        return max(1, min(top, int(v if v is not None else default)))
    except (TypeError, ValueError):
        return default


_NEWS_FIELDS = ("id", "title", "summary", "source", "url", "published", "image")


@app.get("/api/news")
def news(limit: int | None = None) -> JSONResponse:
    conn = _db()
    try:
        snap = store.get(conn, "news")
        if not snap:
            return _no_data("news")
        items = [{**{k: it.get(k) for k in _NEWS_FIELDS}, "aid": media.news_aid(it["id"]), "also": it.get("also") or []}
                 for it in snap["data"]["items"][:_limit(limit, 20, 100)]]
        feeds = {k: {"ok": v.get("ok"), **({"error": v["error"]} if v.get("error") else {})}
                 for k, v in (snap["data"].get("feeds") or {}).items()}
        avail = ["news"] if items else []
        if any(i["image"] for i in items):
            avail.append("images")
        return _resp({**_meta(snap, STALE_AFTER["news"]), "available": avail, "feeds": feeds,
                      "count": len(items), "items": items}, 60)
    finally:
        conn.close()


def _brief_news(it: dict) -> dict:
    return {"aid": media.news_aid(it["id"]), "title": it.get("title"), "source": it.get("source"),
            "published": it.get("published"), "image": it.get("image")}


def _more_news(items: list[dict], aid: str, n: int = 3) -> list[dict]:
    """«Ещё новости»: следующие (более ранние) за этой; в конце ленты — самые свежие."""
    aids = [media.news_aid(i["id"]) for i in items]
    start = aids.index(aid) + 1 if aid in aids else 0
    order = items[start:] + items[:max(0, start - 1)]
    return [_brief_news(i) for i in order if media.news_aid(i["id"]) != aid][:n]


_ARTICLE_FIELDS = ("lead", "html", "author", "origin", "image_caption", "words")


@app.get("/api/news/{aid}")
def news_item(aid: str) -> JSONResponse:
    """Новость целиком для чтения внутри приложения.

    Есть текст — `full: true` и `html` (безопасный, только белый список тегов). Текста ещё нет —
    `pending: true` и заявка сборщику (клиент повторяет запрос). Источник не отдал текст — `full: false`:
    клиент показывает лид, картинку и ссылку «Читать полностью на <источник>»."""
    if not media.is_aid(aid):
        return _resp({"error": "not_found", "detail": "неверный id новости", "available": []}, 60, 404)
    conn = _db()
    try:
        snap = store.get(conn, "news")
        items = snap["data"]["items"] if snap else []
        item = next((i for i in items if media.news_aid(i["id"]) == aid), None)
        art = store.get(conn, f"article:{aid}")
        if not item and not art:
            return _resp({"error": "not_found", "detail": "такой новости нет", "available": []}, 60, 404)
        base = item or art["data"]
        body = {"aid": aid, "id": base["id"], "title": base.get("title"), "source": base.get("source"),
                "site": base.get("site"), "url": base.get("url"), "published": base.get("published"),
                "image": base.get("image"), "summary": base.get("summary") or "",
                "more": _more_news(items, aid)}
        if art and not art["data"].get("text_removed"):
            d = art["data"]
            known = {}
            for i in items:
                a2 = media.news_aid(i["id"])
                for nid in (i["id"], *(i.get("also_ids") or ())):
                    known[nid] = a2
            known.pop(base["id"], None)
            body.update({k: d.get(k) for k in _ARTICLE_FIELDS})
            body["html"] = article.link_internal(d.get("html") or "", known)
            body["image"] = None if d.get("hero_in_text") else (d.get("image") or body["image"])
            body["title"] = body["title"] or d.get("title")
            avail = ["text"] + (["image"] if body["image"] else [])
            return _resp({**body, "full": True, "pending": False, "available": avail,
                          "updated_at": _iso(art["fetched_at"])}, 300)
        partial = {**{k: None for k in _ARTICLE_FIELDS}, "html": None, "full": False}
        if art:  # текст удалён суточной очисткой (старше ARTICLE_TEXT_TTL_DAYS) — заново не качаем
            avail = ["summary"] if body["summary"] else []
            return _resp({**body, **partial, "author": art["data"].get("author"), "origin": art["data"].get("origin"),
                          "pending": False, "reason": "expired", "available": avail,
                          "updated_at": _iso(art["fetched_at"])}, 300)
        fail = store.get(conn, f"article_fail:{aid}")
        now = time.time()
        if fail and (fail["data"].get("tries", 0) >= config.ARTICLE_MAX_TRIES
                     or now - fail["fetched_at"] < config.ARTICLE_RETRY):
            reason = "no_text" if fail["data"].get("status") == "no_text" else "unavailable"
            avail = ["summary"] if body["summary"] else []
            return _resp({**body, **partial, "pending": False, "reason": reason, "available": avail,
                          "updated_at": _iso(fail["fetched_at"])}, 60)
        if not store.ask_article(conn, aid):
            return _resp({**body, **partial, "pending": False, "reason": "busy", "available": []}, 0)
        return _resp({**body, **partial, "pending": True, "available": [], "updated_at": None}, 0)
    finally:
        conn.close()


_VIDEO_FIELDS = ("id", "title", "published", "thumb", "url", "short", "kind", "channel")


@app.get("/api/videos")
def videos(limit: int | None = None) -> JSONResponse:
    """Лента канала + «обзоры матчей» (highlights из снимков матчей, запасной вариант — ролик канала)."""
    conn = _db()
    try:
        snap = store.get(conn, "videos")
        fx = store.get(conn, "fixtures")
        vids = (snap["data"]["items"] if snap else [])
        finished = [f for f in (fx["data"] if fx else []) if f["status"]["finished"] and isinstance(f.get("id"), int)]
        finished = finished[-8:]
        snaps = {}
        for f in finished:
            m = store.get(conn, f"match:{f['id']}")
            if m:
                snaps[str(f["id"])] = m["data"]
        highlights = media.match_highlights(finished, snaps, vids, limit=5)
        if not snap and not highlights:
            return _no_data("videos")
        items = [{k: v.get(k) for k in _VIDEO_FIELDS} for v in vids[:_limit(limit, 15, 40)]]
        avail = [k for k, v in (("videos", items), ("highlights", highlights)) if v]
        if any(v["short"] for v in items):
            avail.append("shorts")
        meta = _meta(snap, STALE_AFTER["videos"]) if snap else \
            {"source": None, "updated_at": None, "age_s": None, "stale": True}
        return _resp({**meta, "available": avail, "highlights": highlights, "count": len(items),
                      "items": items}, 60)
    finally:
        conn.close()


# ---------- здоровье источников ----------

@app.get("/api/health/sources")
def health_sources() -> JSONResponse:
    conn = _db()
    try:
        states = store.source_states(conn)
        collector = states.pop("_collector", None)
        for s in states.values():
            for k in ("last_ok", "last_error"):
                s[k] = _iso(s.get(k))
        hb = None
        try:
            with open(config.HEARTBEAT_FILE) as f:
                hb = round(time.time() - float(f.read().strip()), 1)
        except (OSError, ValueError):
            pass
        ages = store.ages(conn)
        # карточки игроков — только счётчики, иначе список разрастается с каждым чужим игроком
        snaps = {k: v for k, v in ages.items()
                 if not k.startswith(("ctx:", "player:", "player_fail:", "article:", "article_fail:"))}
        players = {"cards": sum(k.startswith("player:") for k in ages),
                   "failed": sum(k.startswith("player_fail:") for k in ages),
                   "queued": conn.execute("SELECT COUNT(*) FROM player_demand").fetchone()[0]}
        articles = {"texts": sum(k.startswith("article:") for k in ages),
                    "failed": sum(k.startswith("article_fail:") for k in ages),
                    "queued": conn.execute("SELECT COUNT(*) FROM article_demand").fetchone()[0]}
        return _resp({"collector": {**(collector or {}), "heartbeat_age_s": hb},
                      "sources": [states[n] for n in config.SOURCE_ORDER if n in states],
                      # медиа — отдельный список: в цепочку данных матча они не входят
                      "media_sources": [states[n] for n in media.MEDIA_SOURCES if n in states],
                      # редкие запросы экрана матча (факты, тур, голоса, трансляция): свой breaker
                      "extra_sources": [states[n] for n in ("fotmob_extra",) if n in states],
                      # бот входа по коду (long polling в сборщике): breaker, офсет, счётчики без личных данных
                      "bot": states.get("telegram_bot"),
                      "snapshots": snaps, "players": players, "articles": articles,
                      "idmap": store.map_count(conn)}, 0)
    finally:
        conn.close()


@app.exception_handler(Exception)
async def _any_error(request: Request, exc: Exception):
    # последняя страховка: даже ошибка чтения снимка не превращается в голый 500 с трейсом
    return _resp({"error": "internal", "detail": type(exc).__name__}, 0, 503)
