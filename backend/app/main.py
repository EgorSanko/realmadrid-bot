"""Мадридиста — API. Только читает снимки сборщика из SQLite; во внешние источники не ходит.

Каждый ответ несёт `source` (откуда снимок), `updated_at` (когда получен), `age_s` и `stale`.
Если все источники упали, сборщик снимок не трогает — здесь отдаётся последний удачный
с его возрастом и кодом 200.
"""
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config, store
from .model import ts
from .predictions import api as predict_api
from .sources import media
from .stream import router as stream_router

VERSION = "0.2.0"

app = FastAPI(title="Мадридиста API", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(stream_router)
predict_api.install(app)  # /api/predict/* — этап 10

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


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health() -> JSONResponse:
    return _resp({"status": "ok", "version": VERSION, "time": datetime.now(timezone.utc).isoformat()}, 0)


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
        nxt = (live or upcoming or [None])[0]
        last = done[-1] if done else None
        sources = {"fixtures": _meta(fx, STALE_AFTER["fixtures"])}
        body = {"next": None, "last": None}
        for key, f in (("next", nxt), ("last", last)):
            if f:
                f2, extra = _match_overlay(conn, f)
                if f2["status"]["finished"] and key == "next":  # следующий успел завершиться
                    f2, extra = f, None
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
        body.update(form=form, laliga=laliga)
        avail = [k for k in ("next", "last", "form", "laliga") if body.get(k)]
        if body["next"] and body["next"].get("venue"):
            avail.append("venue")
        live_now = bool(body["next"] and body["next"]["status"]["live"])
        return _resp({**_meta(fx, STALE_AFTER["fixtures"]), "sources": sources, "available": avail, **body},
                      5 if live_now else 30)
    finally:
        conn.close()


# ---------- матч ----------

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
            return _resp({**m, **meta}, 5 if live else (60 if m["status"]["finished"] else 30))
        # матча нет в снимках: если он есть в календаре — отдаём заголовок и просим сборщика подтянуть
        fx = store.get(conn, "fixtures")
        f = next((f for f in (fx["data"] if fx else []) if str(f["id"]) == match_id), None)
        if not f:
            return _resp({"error": "not_found", "detail": "матча нет ни в снимках, ни в календаре"}, 30, 404)
        store.ask(conn, match_id)
        body = {**f, "events": [], "lineups": None, "stats": None, "shots": [], "momentum": [], "potm": None,
                "highlights": None, "h2h": None, "form": None, "venue": None, "available": [], "pending": True,
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
        live = any(f["status"]["live"] for f in fx["data"])
        return _resp({**_meta(fx, STALE_AFTER["fixtures"]), "tournaments": counts, "matches": fx["data"]},
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
        items = [{**{k: it.get(k) for k in _NEWS_FIELDS}, "also": it.get("also") or []}
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
        snaps = {k: v for k, v in store.ages(conn).items() if not k.startswith("ctx:")}
        return _resp({"collector": {**(collector or {}), "heartbeat_age_s": hb},
                      "sources": [states[n] for n in config.SOURCE_ORDER if n in states],
                      # медиа — отдельный список: в цепочку данных матча они не входят
                      "media_sources": [states[n] for n in media.MEDIA_SOURCES if n in states],
                      "snapshots": snaps, "idmap": store.map_count(conn)}, 0)
    finally:
        conn.close()


@app.exception_handler(Exception)
async def _any_error(request: Request, exc: Exception):
    # последняя страховка: даже ошибка чтения снимка не превращается в голый 500 с трейсом
    return _resp({"error": "internal", "detail": type(exc).__name__}, 0, 503)
