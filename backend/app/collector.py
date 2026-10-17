"""Сборщик: отдельный процесс (контейнер rm-v2-collector, network_mode: host).

Опрашивает источники по расписанию, нормализует и пишет снимки в SQLite.
API во внешние источники не ходит никогда — только читает эти снимки.

  python -m app.collector                       # демон
  python -m app.collector once team|mapping     # один цикл команды / сопоставления id
  python -m app.collector once news|videos      # один цикл новостей (RSS) / видео (YouTube)
  python -m app.collector once match <id>       # один цикл матча (цепочка источников)
  python -m app.collector once player <id>      # карточка игрока (FotMob → SofaScore)
  python -m app.collector once players          # все игроки состава Реала (с лимитом в минуту)
  python -m app.collector once avatars          # заявки на аватары пользователей (t.me через туннель)
  python -m app.collector once settle           # начислить очки прогнозов за сыгранные матчи
  python -m app.collector live <id> [--cycles 6] [--interval 12]   # режим матча на любом матче
  python -m app.collector find-live             # идущие сейчас матчи по FotMob

Цепочка для каждого типа данных: FotMob → SofaScore → ESPN → LiveScore
(LiveScore — только для матча). Первый удачный источник пишет снимок;
если упали все — снимок не трогаем, API отдаёт последний удачный с возрастом.
"""
import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from . import avatars, config, store
from .predictions import db as predictions_db
from .predictions.service import PredictionService, utcnow
from .predictions.snapshot_provider import SnapshotProvider
from .model import iso_utc, name_key, same_person, same_team, ts
from .sources import espn, fotmob, livescore, media, sofascore
from .sources.base import NotFound, SourceError

log = logging.getLogger("collector")


def _ymd(iso: str, sep: str = "") -> str:
    return iso[:10].replace("-", sep)


class Collector:
    def __init__(self, conn):
        self.conn = conn
        self.fm = fotmob.FotMob()
        self.ss = sofascore.SofaScore()
        self.es = espn.ESPN()
        self.ls = livescore.LiveScore()
        self.sources = {"fotmob": self.fm, "sofascore": self.ss, "espn": self.es, "livescore": self.ls}
        self.match_due: dict[str, float] = {}     # id → когда обновлять
        self.match_cycle: dict[str, int] = {}     # счётчик циклов (для «лёгких» запросов SofaScore/LiveScore)
        self.parts: dict[tuple, dict] = {}        # кэш частей матча у многоэндпоинтных источников
        self.sofa_events: list = []               # последние события Реала в SofaScore
        self.miss: dict[tuple, float] = {}        # (источник, id) → когда не нашли сопоставление
        self.ls_by_date: dict[str, dict] = {}
        # медиа — свои HTTP-клиенты (breaker и счётчики у каждого сайта), в цепочку матча не входят
        self.media = media.make_sources()
        self.cycles = {"team": 0, "mapping": 0, "match": 0, "match_failed": 0, "news": 0, "videos": 0,
                       "player": 0, "player_failed": 0}
        self.player_req: deque = deque()          # время запросов карточек игроков (лимит в минуту)
        self.last_team = 0.0
        self.last_mapping = 0.0
        self.last_news = 0.0
        self.last_videos = 0.0
        self.last_avatars = 0.0
        self._avatar_fetch = None                  # curl_cffi через SOCKS-туннель, создаётся при первой заявке
        self._avatar_close = None
        self._avatar_task: asyncio.Task | None = None
        # начисление очков прогнозов: раз в SETTLE_INTERVAL и сразу, как увидели новый/исправленный итог
        self.last_settle = 0.0
        self.settle_due = False
        self.predict_clock = utcnow                # подменяется в тестах
        self._predict: PredictionService | None = None

    async def close(self):
        for s in (*self.sources.values(), *self.media.values()):
            await s.close()
        if self._avatar_task is not None and not self._avatar_task.done():
            self._avatar_task.cancel()
        if self._avatar_close is not None:
            await self._avatar_close()

    # ================= аватары пользователей (заявки API при входе) =================
    async def tick_avatars(self, now: float, limit: int = 2) -> list:
        """Скачать до `limit` аватаров из avatar_queue (predictions.db) через туннель t.me."""
        if now - self.last_avatars < config.AVATAR_INTERVAL:
            return []
        self.last_avatars = now
        try:
            done = await self._avatars_once(limit)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("avatars: ошибка (продолжаю)")
            return []
        for uid, res in done:
            log.info("avatar %s → %s", uid, res)
        self.cycles["avatars"] = self.cycles.get("avatars", 0) + len(done)
        return done

    async def _avatars_once(self, limit: int) -> list:
        conn = predictions_db.connect()
        try:
            if not conn.execute("SELECT 1 FROM avatar_queue LIMIT 1").fetchone():
                return []
            if self._avatar_fetch is None:
                self._avatar_fetch, self._avatar_close = avatars.curl_fetch(config.TG_PROXY, config.SOFA_TIMEOUT)
            done = await avatars.process(conn, self._avatar_fetch, limit=limit)
        finally:
            conn.close()
        return done

    # ================= прогнозы: начисление очков =================

    def _predictions(self) -> PredictionService:
        if self._predict is None:
            # матчи — из тех же снимков, что пишет сборщик; прогнозы — DATA_DIR/predictions.db
            self._predict = PredictionService(SnapshotProvider(), clock=self.predict_clock)
        return self._predict

    async def tick_settle(self, now: float, force: bool = False) -> list | None:
        """settle_pending(): матчи, которые начались и ещё не рассчитаны, и исправления итогов за 14 дней.

        Идемпотентно: неизменившийся итог — 'unchanged', очки не удваиваются. Лёгкий проход — раз в 10 мин;
        вне очереди — когда снимок матча впервые стал «завершён» или поменялся итог (счёт, голы).
        """
        if not (force or self.settle_due or now - self.last_settle >= config.SETTLE_INTERVAL):
            return None
        self.last_settle = now
        self.settle_due = False
        try:
            res = await asyncio.to_thread(self._predictions().settle_pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("settle: ошибка (продолжаю)")
            return None
        for r in res:
            if r["result"] in ("settled", "resettled", "voided"):
                log.info("settle %s → %s: прогнозов %s, изменено %s", r["match_id"], r["result"],
                         r["predictions"], r["changed"])
        self.cycles["settle"] = self.cycles.get("settle", 0) + 1
        return res

    def _results_sig(self) -> tuple:
        """Итоги сыгранных/идущих матчей календаря — заметить исправление результата после refresh_team."""
        return tuple((f.get("id"), f["status"]["state"], f["home"].get("score"), f["away"].get("score"))
                     for f in self._fixtures() if f["status"].get("finished") or f["status"].get("live"))

    # ================= медиа: новости и видео =================

    def _squad_ids(self) -> set[int] | None:
        """Игроки и тренер из снимка команды — для фильтра новостей. Нет снимка — None (все фамилии)."""
        t = store.get(self.conn, "team")
        if not t:
            return None
        d = t["data"]
        ids = {p["id"] for line in (d.get("squad") or {}).values() for p in line if p.get("id")}
        if (d.get("coach") or {}).get("id"):
            ids.add(d["coach"]["id"])
        return ids or None

    async def refresh_news(self, og_limit: int | None = None) -> dict:
        """Ленты RSS → фильтр «про Реал» → без дублей → снимок `news`. Упали все ленты — снимок не трогаем."""
        self.cycles["news"] += 1
        self.last_news = time.time()
        feeds, fresh, ok_sites = {}, [], []
        squad = self._squad_ids()

        async def pull(f: media.Feed):
            src = self.media[f.site]
            if not src.available():
                return f, None, "disabled" if src.disabled() else "breaker open"
            try:
                return f, media.parse_rss(f, await src.text(f.url, kind=f.key)), None
            except (SourceError, ValueError) as e:
                return f, None, str(e)[:200]

        for f, items, err in await asyncio.gather(*(pull(f) for f in media.NEWS_FEEDS)):
            if items is None:
                feeds[f.key] = {"ok": False, "error": err}
                continue
            matched = [i for i in items if media.is_about_rm(i, squad)]
            feeds[f.key] = {"ok": True, "items": len(items), "matched": len(matched)}
            fresh += matched
            if f.site not in ok_sites:
                ok_sites.append(f.site)
        if not ok_sites:
            log.warning("news: все ленты недоступны: %s", feeds)
            return {"news": "stale", "feeds": feeds}
        prev = store.get(self.conn, "news")
        merged = media.merge_news((prev["data"]["items"] if prev else []), fresh, squad)
        og = await self._news_images(merged, config.NEWS_OG_PER_CYCLE if og_limit is None else og_limit)
        store.put(self.conn, "news", "+".join(ok_sites),
                  {"items": merged, "feeds": feeds, "og_fetched": og})
        return {"news": len(merged), "fresh": len(fresh), "og": og, "feeds": feeds}

    async def _news_images(self, items: list[dict], limit: int) -> int:
        """У Sports.ru в RSS нет картинок: берём og:image со страницы — только для новостей про Реал,
        не больше `limit` за цикл, по одному разу на новость."""
        src = self.media["sportsru_pages"]
        n = 0
        for it in items[:40]:
            if n >= limit or not src.available():
                break
            if it.get("image") or it.get("img_tried") or it.get("site") != "sportsru":
                continue
            n += 1
            it["img_tried"] = True
            try:
                page = await src.text(it["url"], kind="og")
            except SourceError as e:
                log.info("news og: %s: %s", it["url"], e)
                continue
            it["image"] = media.news_image_path(media.og_image(page))
        return n

    async def refresh_videos(self) -> dict:
        """RSS официального канала → снимок `videos` (последние 40). Обзоры матчей собирает API
        из снимков матчей, здесь — только лента канала."""
        self.cycles["videos"] += 1
        self.last_videos = time.time()
        src = self.media["youtube"]
        try:
            fresh = media.parse_youtube(await src.text(media.YT_FEED, kind="channel"))
        except (SourceError, ValueError) as e:
            log.warning("videos: youtube: %s", e)
            return {"videos": "stale", "error": str(e)[:200]}
        if not fresh:
            return {"videos": "stale", "error": "пустая лента"}
        prev = store.get(self.conn, "videos")
        merged = media.merge_videos((prev["data"]["items"] if prev else []), fresh)
        store.put(self.conn, "videos", "youtube", {"items": merged})
        return {"videos": len(merged), "fresh": len(fresh), "shorts": sum(v["short"] for v in fresh)}

    # ================= команда / календарь / таблицы =================

    async def refresh_team(self) -> dict:
        """Один запрос FotMob даёт календарь, таблицы и состав. Не вышло — резервы по каждому типу."""
        self.cycles["team"] += 1
        self.last_team = time.time()
        done = {}
        raw = None
        try:
            raw = await self.fm.team()
        except SourceError as e:
            log.warning("team: fotmob: %s", e)
        if raw:
            fixtures = fotmob.normalize_fixtures(raw)
            self._attach_ids(fixtures)
            with self.conn:
                store.put(self.conn, "fixtures", "fotmob", fixtures)
                store.put(self.conn, "tables", "fotmob", fotmob.normalize_tables(raw))
                team = fotmob.normalize_team(raw)
                store.put(self.conn, "team", "fotmob", team)
                store.put(self.conn, "ctx:team", "fotmob", _ctx_from_team(team))
            return {"fixtures": "fotmob", "tables": "fotmob", "team": "fotmob"}

        for kind, fn in (("fixtures", self._fixtures_fallback), ("tables", self._tables_fallback),
                         ("team", self._team_fallback)):
            got = None
            for name, src in (("sofascore", self.ss), ("espn", self.es)):
                if not src.available():
                    continue
                try:
                    data = await fn(name)
                except SourceError as e:
                    log.warning("%s: %s: %s", kind, name, e)
                    continue
                if data:
                    store.put(self.conn, kind, name, data)
                    got = name
                    break
            done[kind] = got or "stale"
        return done

    def _ctx(self, source: str, match_id=None) -> dict:
        ctx = {"teams": store.map_all(self.conn, "team", source),
               "matches": store.map_all(self.conn, "match", source),
               "numbers": {}, "names": {}, "last": {}}
        t = store.get(self.conn, "ctx:team")
        if t:
            ctx["names"].update(t["data"]["names"])
            ctx["last"].update(t["data"]["last"])
        if match_id is not None:
            ctx["match_id"] = int(match_id) if str(match_id).isdigit() else None
            c = store.get(self.conn, f"ctx:match:{match_id}")
            if c:
                ctx["numbers"] = c["data"]["numbers"]
                ctx["names"].update(c["data"]["names"])
                ctx["last"].update(c["data"]["last"])
        return ctx

    async def _sofa_team_events(self) -> list:
        last = await self.ss.team_events("last")
        nxt = await self.ss.team_events("next")
        self.sofa_events = (last.get("events") or []) + (nxt.get("events") or [])
        return self.sofa_events

    async def _espn_schedules(self, leagues=None) -> dict:
        out = {}
        for lid in leagues or config.LEAGUES:
            slug = config.LEAGUES[lid]["espn"]
            out[slug] = []
            for upcoming in (False, True):
                try:
                    out[slug].append(await self.es.schedule(slug, upcoming))
                except NotFound:
                    pass
        return out

    async def _fixtures_fallback(self, name):
        if name == "sofascore":
            evs = await self._sofa_team_events()
            return sofascore.normalize_fixtures(evs, self._ctx("sofascore"))
        return espn.normalize_fixtures(await self._espn_schedules(), self._ctx("espn"))

    async def _tables_fallback(self, name):
        out = []
        if name == "sofascore":
            evs = self.sofa_events or await self._sofa_team_events()
            seasons = {}
            for e in evs:
                ut = ((e.get("tournament") or {}).get("uniqueTournament") or {}).get("id")
                if ut in (8, 7):
                    seasons[ut] = max(seasons.get(ut, 0), (e.get("season") or {}).get("id") or 0)
            for lid in config.TABLE_LEAGUES:
                ut = config.LEAGUES[lid]["sofa"]
                if seasons.get(ut):
                    t = sofascore.normalize_table(await self.ss.standings(ut, seasons[ut]), lid, self._ctx("sofascore"))
                    if t:
                        out.append(t)
        else:
            for lid in config.TABLE_LEAGUES:
                t = espn.normalize_table(await self.es.standings(config.LEAGUES[lid]["espn"]), lid, self._ctx("espn"))
                if t:
                    out.append(t)
        return out

    async def _team_fallback(self, name):
        if name == "sofascore":
            return sofascore.normalize_team(await self.ss.players(), self._ctx("sofascore"))
        return espn.normalize_team(await self.es.roster(), self._ctx("espn"))

    def _attach_ids(self, fixtures: list):
        for f in fixtures:
            fid = f["ids"].get("fotmob")
            if fid:
                for src in ("sofascore", "espn", "livescore"):
                    f["ids"][src] = f["ids"].get(src) or store.from_fotmob(self.conn, "match", src, fid)

    # ================= сопоставление id =================

    async def refresh_mapping(self) -> dict:
        """FotMob-календарь ↔ SofaScore/ESPN по дате и соперникам (+ id команд). Раз в 6 ч."""
        self.cycles["mapping"] += 1
        self.last_mapping = time.time()
        snap = store.get(self.conn, "fixtures")
        fixtures = [f for f in (snap["data"] if snap else []) if isinstance(f.get("id"), int)]
        res = {"fixtures": len(fixtures), "sofascore": 0, "espn": 0}
        if not fixtures:
            return res
        if self.ss.available():
            try:
                evs = await self._sofa_team_events()
                res["sofascore"] = self._map_list(fixtures, "sofascore", [
                    (str(e.get("id")), e.get("startTimestamp"), (e.get("homeTeam") or {}).get("name"),
                     (e.get("awayTeam") or {}).get("name"), (e.get("homeTeam") or {}).get("id"),
                     (e.get("awayTeam") or {}).get("id"), None) for e in evs])
            except SourceError as e:
                log.warning("mapping: sofascore: %s", e)
        if self.es.available():
            try:
                leagues = sorted({f["tournament"]["id"] for f in fixtures} | {87, 42})
                sched = await self._espn_schedules(leagues)
                items = []
                for f in espn.normalize_fixtures(sched):
                    items.append((str(f["ids"]["espn"]), ts(f["kickoff"]), f["home"]["name"], f["away"]["name"],
                                  f["_espn_team_ids"][0], f["_espn_team_ids"][1], f["ids"]["espn_league"]))
                res["espn"] = self._map_list(fixtures, "espn", items)
            except SourceError as e:
                log.warning("mapping: espn: %s", e)
        if self.ss.available():
            try:
                res["players"] = self._map_squad_players(await self.ss.players())
            except SourceError as e:
                log.warning("mapping: sofascore players: %s", e)
        self._attach_ids(snap["data"])  # те же объекты, что и fixtures
        store.put(self.conn, "fixtures", snap["source"], snap["data"], fetched_at=snap["fetched_at"])
        return res

    def _map_squad_players(self, raw: dict) -> int:
        """Игроки Реала: SofaScore team/2829/players ↔ состав FotMob по имени; если у обоих есть дата
        рождения — она обязана совпасть. Неоднозначно (два кандидата) — не сопоставляем."""
        t = store.get(self.conn, "team")
        squad = [p for line in ((t or {}).get("data", {}).get("squad") or {}).values() for p in line if p.get("id")]
        n = 0
        with self.conn:
            for it in raw.get("players") or []:
                sp = it.get("player") or {}
                birth = iso_utc_date(sp.get("dateOfBirthTimestamp"))
                cands = [p for p in squad if same_person(p.get("name"), sp.get("name"))
                         and (not birth or not p.get("birth") or p["birth"][:10] == birth)]
                if len(cands) == 1 and sp.get("id"):
                    store.map_set(self.conn, "player", "sofascore", sp["id"], cands[0]["id"], "squad")
                    n += 1
        return n

    def _map_list(self, fixtures, source, items) -> int:
        n = 0
        with self.conn:
            for sid, start, hname, aname, hid, aid, note in items:
                if not start:
                    continue
                near = [f for f in fixtures
                        if ts(f["kickoff"]) is not None and abs(ts(f["kickoff"]) - float(start)) <= 3 * 3600]
                for f in near:
                    names_ok = same_team(f["home"]["name"], hname) and same_team(f["away"]["name"], aname)
                    # Реал не играет два матча за 3 часа: единственный кандидат с Реалом на той же
                    # стороне — тот же матч, даже если имена соперника не совпали
                    # («Racing Santander» / «Real Racing Club»)
                    real_side_ok = len(near) == 1 and (
                        (f["home"]["id"] == config.TEAM_ID and same_team(hname, "Real Madrid")) or
                        (f["away"]["id"] == config.TEAM_ID and same_team(aname, "Real Madrid")))
                    if names_ok or real_side_ok:
                        break
                else:
                    # дальние туры без назначенного времени: у источников разные даты-заглушки.
                    # Пара «хозяин–гость» за ±4 дня не повторяется — сопоставляем по ней.
                    f = next((f for f in fixtures if ts(f["kickoff"]) is not None
                              and abs(ts(f["kickoff"]) - float(start)) <= 4 * 86400
                              and same_team(f["home"]["name"], hname) and same_team(f["away"]["name"], aname)), None)
                    if not f:
                        continue
                store.map_set(self.conn, "match", source, sid, f["id"], note)
                store.map_set(self.conn, "team", source, hid, f["home"]["id"])
                store.map_set(self.conn, "team", source, aid, f["away"]["id"])
                n += 1
        return n

    async def _match_info(self, fid) -> dict | None:
        """Дата и соперники матча — для поиска id в резервных источниках."""
        for key in (f"match:{fid}", "fixtures"):
            s = store.get(self.conn, key)
            if not s:
                continue
            items = [s["data"]] if key.startswith("match:") else s["data"]
            for f in items:
                if str(f.get("id")) == str(fid) or str((f.get("ids") or {}).get("fotmob")) == str(fid):
                    return {"kickoff": f.get("kickoff"), "home": f["home"]["name"], "away": f["away"]["name"],
                            "home_id": f["home"].get("id"), "away_id": f["away"].get("id"),
                            "league": (f.get("tournament") or {}).get("id")}
        return None

    def _missed(self, source: str, fid) -> bool:
        """Недавно не нашли id — не тратим запросы на повторный поиск 10 минут."""
        return time.time() - self.miss.get((source, str(fid)), 0) < 600

    async def _sofa_id(self, fid) -> str | None:
        sid = store.from_fotmob(self.conn, "match", "sofascore", fid)
        if sid or self._missed("sofascore", fid):
            return sid
        info = await self._match_info(fid)
        if not info or not info["kickoff"]:
            return None
        self.miss[("sofascore", str(fid))] = time.time()
        # сначала события Реала (дёшево); для чужого идущего матча — общий список лайва
        # (scheduled-events/{дата} у SofaScore больше нет: 404)
        cand = self.sofa_events or (await self._sofa_team_events())
        if not any(_sofa_match(e, info) for e in cand) and abs(time.time() - (ts(info["kickoff"]) or 0)) < 4 * 3600:
            cand = (await self.ss.live_events()).get("events") or []
        for e in cand:
            if _sofa_match(e, info):
                with self.conn:
                    store.map_set(self.conn, "match", "sofascore", e["id"], fid, "auto")
                    store.map_set(self.conn, "team", "sofascore", (e.get("homeTeam") or {}).get("id"), info["home_id"])
                    store.map_set(self.conn, "team", "sofascore", (e.get("awayTeam") or {}).get("id"), info["away_id"])
                self.miss.pop(("sofascore", str(fid)), None)
                return str(e["id"])
        return None

    async def _ls_id(self, fid) -> str | None:
        eid = store.from_fotmob(self.conn, "match", "livescore", fid)
        if eid or self._missed("livescore", fid):
            return eid
        info = await self._match_info(fid)
        if not info or not info["kickoff"]:
            return None
        self.miss[("livescore", str(fid))] = time.time()
        day = _ymd(info["kickoff"])
        if day not in self.ls_by_date:
            self.ls_by_date[day] = await self.ls.by_date(day)
        eid, exact = livescore.find_event(self.ls_by_date[day], info["home"], info["away"], info["kickoff"])
        if not eid:
            return None
        sb = await self.ls.part("scoreboard", eid)
        ids = livescore.fotmob_ids(sb)
        if ids["match"] and str(ids["match"]) != str(fid):
            # у части лиг FotMob сменил id (1000xxxxxx), а LiveScore помнит старый —
            # тогда верим точному совпадению обеих команд и времени начала
            if not exact:
                log.warning("livescore: Eid %s указывает на FotMob %s, а не %s — не сопоставляю",
                            eid, ids["match"], fid)
                return None
            log.info("livescore: Eid %s: в Pids FotMob %s (≠ %s), но команды и время совпали", eid, ids["match"], fid)
            note = "date+teams (pids differ)"
        else:
            note = "pids" if ids["match"] else "date+teams"
        with self.conn:
            store.map_set(self.conn, "match", "livescore", eid, fid, note)
            if note == "pids":
                for side in ("home", "away"):
                    if ids[side] and ids[f"sofa_{side}"]:
                        store.map_set(self.conn, "team", "sofascore", ids[f"sofa_{side}"], ids[side], "livescore-pids")
        self.parts[("livescore", fid, "scoreboard")] = sb
        self.miss.pop(("livescore", str(fid)), None)
        return str(eid)

    # ================= игроки =================

    def _squad_player_ids(self) -> list[str]:
        t = store.get(self.conn, "team")
        if not t:
            return []
        return [str(p["id"]) for line in (t["data"].get("squad") or {}).values() for p in line if p.get("id")]

    def player_ttl(self, pid, data: dict | None) -> int:
        """Свои — раз в 6 ч (обновляются заранее), чужие — кэш 24 ч."""
        own = str(pid) in self._squad_player_ids() or ((data or {}).get("team") or {}).get("id") == config.TEAM_ID
        return config.PLAYER_INTERVAL if own else config.PLAYER_FOREIGN_TTL

    def _player_budget(self, now: float, cost: int = 1) -> bool:
        """Не больше PLAYER_RATE_PER_MIN запросов карточек в минуту (FotMob и SofaScore вместе)."""
        while self.player_req and self.player_req[0] < now - 60:
            self.player_req.popleft()
        return len(self.player_req) + cost <= config.PLAYER_RATE_PER_MIN

    def _spend(self, n: int = 1):
        now = time.time()
        self.player_req.extend([now] * n)

    async def refresh_player(self, pid) -> dict | None:
        """FotMob → SofaScore (если знаем id игрока у SofaScore). Не вышло — снимок не трогаем,
        пишем `player_fail:<id>`, чтобы API ответил честной ошибкой вместо вечного «загружаем»."""
        pid = str(pid)
        self.cycles["player"] += 1
        errors, not_found = {}, False
        for name in ("fotmob", "sofascore"):
            src = self.sources[name]
            if not src.available():
                errors[name] = "disabled" if src.disabled() else "breaker open"
                continue
            try:
                p = await getattr(self, f"_player_{name}")(pid)
            except NotFound as e:
                errors[name] = f"not found: {e}"[:200]
                if name == "fotmob":
                    not_found = True
                    break  # у FotMob нет такого id — резерв искать нечего
                continue
            except SourceError as e:
                errors[name] = str(e)[:200]
                continue
            except Exception as e:  # ошибка нормализатора не роняет такт
                log.exception("player %s: %s: нормализатор упал", pid, name)
                errors[name] = f"normalize: {type(e).__name__}: {e}"[:200]
                continue
            if not p:
                errors[name] = "no id mapping"
                continue
            p["fallback_errors"] = errors or None
            self._merge_team_status(pid, p)
            with self.conn:
                store.put(self.conn, f"player:{pid}", name, p)
                self.conn.execute("DELETE FROM snapshots WHERE key=?", (f"player_fail:{pid}",))
            return p
        self.cycles["player_failed"] += 1
        store.put(self.conn, f"player_fail:{pid}", "collector", {"errors": errors, "not_found": not_found})
        log.warning("player %s: нет данных: %s", pid, errors)
        return None

    async def _player_fotmob(self, pid):
        self._spend(1)
        return fotmob.normalize_player(await self.fm.player(pid))

    async def _player_sofascore(self, pid):
        sid = store.from_fotmob(self.conn, "player", "sofascore", pid)
        if not sid:
            return None
        self._spend(2)
        raw = await self.ss.player(sid)
        try:
            last = await self.ss.player_events(sid)
        except NotFound:
            last = None
        ctx = {"fotmob_id": int(pid), "teams": store.map_all(self.conn, "team", "sofascore"),
               "matches": store.map_all(self.conn, "match", "sofascore")}
        return sofascore.normalize_player(raw, last, ctx)

    def _merge_team_status(self, pid: str, p: dict):
        """У FotMob в playerData нет дисквалификаций — берём статус из лазарета снимка команды."""
        if p.get("status"):
            return
        t = store.get(self.conn, "team")
        inj = next((i for i in ((t or {}).get("data", {}).get("injuries") or []) if str(i.get("id")) == pid), None)
        if inj:
            p["status"] = {"type": inj.get("type") or "injury", "name": None,
                           "expected_return": inj.get("expected_return"), "updated": None}
            if "status" not in p["available"]:
                p["available"].append("status")

    def _recent_fail(self, pid: str, now: float) -> bool:
        """Отказ — по записи player_fail в базе (её же читает API), а не по памяти процесса:
        иначе после ручной чистки или перезапуска API и сборщик разошлись бы."""
        row = self.conn.execute("SELECT fetched_at FROM snapshots WHERE key=?", (f"player_fail:{pid}",)).fetchone()
        return bool(row) and now - row[0] < config.PLAYER_FAIL_RETRY

    def players_due(self, now: float) -> list[str]:
        """Игроки состава, у которых снимок старше 6 ч (или его нет), кроме недавно не давшихся."""
        out = []
        for pid in self._squad_player_ids():
            if self._recent_fail(pid, now):
                continue
            row = self.conn.execute("SELECT fetched_at FROM snapshots WHERE key=?", (f"player:{pid}",)).fetchone()
            if not row or now - row[0] >= config.PLAYER_INTERVAL:
                out.append(pid)
        return out

    async def tick_players(self, now: float, squad: bool = True, per_tick: int = 2) -> list[str]:
        """Один такт: сначала заявки API (человек ждёт), потом плановое обновление состава.
        Лимит в минуту общий; за такт — не больше per_tick игроков, чтобы не задерживать лайв."""
        done = []
        for pid in store.peek_player_demand(self.conn, 10):
            if len(done) >= per_tick or not self._player_budget(now):
                return done
            store.drop_player_demand(self.conn, pid)
            snap = store.get(self.conn, f"player:{pid}")
            if snap and now - snap["fetched_at"] < self.player_ttl(pid, snap["data"]):
                continue  # уже свежий (успели подтянуть по другой заявке)
            if self._recent_fail(pid, now):
                continue  # недавно не вышло — API уже отдаёт ошибку из player_fail
            p = await self.refresh_player(pid)
            done.append(pid)
            log.info("player demand %s → %s", pid, p and p["source"])
        if squad:
            for pid in self.players_due(now):
                if len(done) >= per_tick or not self._player_budget(now):
                    break
                p = await self.refresh_player(pid)
                done.append(pid)
                log.info("player %s → %s", pid, p and p["source"])
        return done

    # ================= матч =================

    async def refresh_match(self, fid, live: bool = False) -> dict | None:
        """Цепочка источников для одного матча. Возвращает снимок или None (все упали)."""
        fid = str(fid)
        self.cycles["match"] += 1
        n = self.match_cycle[fid] = self.match_cycle.get(fid, 0) + 1
        full = (not live) or n % 3 == 1   # в лайве тяжёлые части у резервов — раз в 3 цикла
        prev = store.get(self.conn, f"match:{fid}")
        errors = {}
        for name in config.SOURCE_ORDER:
            src = self.sources[name]
            if not src.available():
                errors[name] = "disabled" if src.disabled() else "breaker open"
                continue
            try:
                m = await getattr(self, f"_match_{name}")(fid, full)
            except SourceError as e:
                errors[name] = str(e)[:200]
                continue
            except Exception as e:  # ошибка нормализатора не должна ронять цикл
                log.exception("match %s: %s: нормализатор упал", fid, name)
                errors[name] = f"normalize: {type(e).__name__}: {e}"[:200]
                continue
            if not m:
                errors[name] = "no id mapping"
                continue
            m["fetched_from"] = name
            for other in ("sofascore", "espn", "livescore"):
                m["ids"][other] = m["ids"].get(other) or store.from_fotmob(self.conn, "match", other, fid)
            m["fallback_errors"] = errors or None
            # новый или исправленный итог — очки прогнозов пересчитать в этом же такте
            if m["status"]["finished"] and _result_of(m) != _result_of((prev or {}).get("data")):
                self.settle_due = True
            # момент, когда впервые увидели «завершён» — для окна +30 мин
            seen = (prev or {}).get("data", {}).get("finished_seen_at") if prev else None
            m["finished_seen_at"] = seen or (time.time() if m["status"]["finished"] else None)
            if not m["status"]["finished"]:
                m["finished_seen_at"] = None
            store.put(self.conn, f"match:{fid}", name, m)
            return m
        self.cycles["match_failed"] += 1
        log.warning("match %s: все источники недоступны: %s", fid, errors)
        return None

    async def _match_fotmob(self, fid, full):
        raw = await self.fm.match(fid)
        m = fotmob.normalize_match(raw)
        if m.get("lineups"):
            store.put(self.conn, f"ctx:match:{fid}", "fotmob", _ctx_from_match(m))
        return m

    async def _match_sofascore(self, fid, full):
        sid = await self._sofa_id(fid)
        if not sid:
            return None
        key = ("sofascore", fid)
        b = self.parts.setdefault(key, {})
        b["event"] = await self.ss.event(sid)
        st = ((b["event"].get("event") or {}).get("status") or {}).get("type")
        if st != "notstarted" or full:
            b["incidents"] = await self.ss.part(sid, "incidents")
        if full or "lineups" not in b:
            for part in ("lineups", "statistics", "shotmap", "graph"):
                if st == "notstarted" and part != "lineups":
                    continue
                b[part] = await self.ss.part(sid, part)
        if st == "finished" and (full or "best" not in b):
            b["best"] = await self.ss.part(sid, "best-players/summary")
        m = sofascore.normalize_match(b, self._ctx("sofascore", fid))
        # заодно запоминаем id игроков обеих команд: SofaScore ↔ FotMob (по номеру и стороне из составов
        # FotMob этого же матча) — это резерв для карточек чужих игроков
        with self.conn:
            for side in ("home", "away"):
                lu = (m.get("lineups") or {}).get(side) or {}
                for p in (lu.get("starters") or []) + (lu.get("subs") or []):
                    if p.get("id") and p.get("source_id"):
                        store.map_set(self.conn, "player", "sofascore", p["source_id"], p["id"], "lineup")
        return m

    async def _match_espn(self, fid, full):
        eid = store.from_fotmob(self.conn, "match", "espn", fid)
        if not eid:
            return None
        row = self.conn.execute("SELECT note FROM idmap WHERE kind='match' AND source='espn' AND source_id=?",
                                (eid,)).fetchone()
        slug = row[0] if row and row[0] else None
        if not slug:
            info = await self._match_info(fid)
            slug = config.LEAGUES.get((info or {}).get("league"), {}).get("espn")
        if not slug:
            return None
        return espn.normalize_match(await self.es.summary(slug, eid), self._ctx("espn", fid))

    async def _match_livescore(self, fid, full):
        eid = await self._ls_id(fid)
        if not eid:
            return None
        b = {}
        for part in ("scoreboard", "incidents", "lineups", "statistics"):
            k = ("livescore", fid, part)
            if part in ("scoreboard", "incidents") or full or k not in self.parts:
                try:
                    self.parts[k] = await self.ls.part(part, eid)
                except NotFound:
                    self.parts[k] = {}
            b[part] = self.parts[k]
        return livescore.normalize_match(b, self._ctx("livescore", fid))

    # ================= расписание =================

    def _fixtures(self) -> list:
        s = store.get(self.conn, "fixtures")
        return s["data"] if s else []

    def window(self, now: float) -> list[str]:
        """Матчи в «окне»: от −75 мин до +2,5 ч от начала, после «завершён» — ещё 30 мин."""
        out = []
        cands = [(str(f["id"]), ts(f["kickoff"]), f["status"]) for f in self._fixtures()
                 if isinstance(f.get("id"), int) and f.get("kickoff")]
        cands += [(str(d), None, None) for d in config.DEBUG_LIVE_MATCHES]
        for fid, ko, fst in cands:
            snap = store.get(self.conn, f"match:{fid}")
            st = (snap["data"]["status"] if snap else fst) or {}
            fin_seen = snap["data"].get("finished_seen_at") if snap else None
            if ko is None and snap and snap["data"].get("kickoff"):
                ko = ts(snap["data"]["kickoff"])
            if st.get("state") in ("postponed", "cancelled", "abandoned"):
                continue
            if ko is None:  # отладочный матч без данных — пока не узнаем время, держим в окне
                if not st.get("finished") or not fin_seen or now - fin_seen <= config.WINDOW_AFTER_FINISH:
                    out.append(fid)
                continue
            if not (ko - config.WINDOW_BEFORE <= now <= ko + config.WINDOW_HARD_CAP):
                if fid not in [str(d) for d in config.DEBUG_LIVE_MATCHES]:
                    continue
            if st.get("finished"):
                if fin_seen and now - fin_seen <= config.WINDOW_AFTER_FINISH:
                    out.append(fid)
            elif st.get("live") or now <= ko + config.WINDOW_AFTER_START:
                out.append(fid)
        return list(dict.fromkeys(out))

    def last_next(self, now: float) -> list[str]:
        fx = [f for f in self._fixtures() if isinstance(f.get("id"), int) and f.get("kickoff")]
        done = [f for f in fx if f["status"]["finished"]]
        upcoming = [f for f in fx if not f["status"]["finished"]
                    and f["status"]["state"] not in ("cancelled", "postponed") and ts(f["kickoff"]) > now - 4 * 3600]
        out = []
        if done:
            out.append(str(done[-1]["id"]))
        if upcoming:
            out.append(str(upcoming[0]["id"]))
        return out

    def write_state(self):
        with self.conn:
            for name, s in (*self.sources.items(), *self.media.items()):
                store.put_source_state(self.conn, name, s.snapshot())
            store.put_source_state(self.conn, "_collector", {
                "pid": os.getpid(), "cycles": self.cycles, "last_team": self.last_team,
                "last_mapping": self.last_mapping, "last_news": self.last_news, "last_videos": self.last_videos,
                "in_window": self.window(time.time()),
                "disabled": sorted(config.disabled_sources()),
            })

    async def run(self, stop: asyncio.Event):
        log.info("collector: старт; DB=%s; debug live=%s", config.DB_PATH, config.DEBUG_LIVE_MATCHES)
        next_state = 0.0
        while not stop.is_set():
            now = time.time()
            try:
                if now - self.last_team >= config.TEAM_INTERVAL:
                    before = self._results_sig()
                    log.info("team: %s", await self.refresh_team())
                    if self._results_sig() != before:
                        self.settle_due = True
                if now - self.last_mapping >= config.MAPPING_INTERVAL:
                    log.info("mapping: %s", await self.refresh_mapping())
                win = self.window(now)
                # медиа — после команды (нужен состав для фильтра). Ленты качаются параллельно,
                # такт держат не дольше одного таймаута; в окне матча страницы ради картинок не открываем
                if now - self.last_news >= config.NEWS_INTERVAL:
                    r = await self.refresh_news(og_limit=0 if win else config.NEWS_OG_PER_CYCLE)
                    log.info("news: %s", {k: v for k, v in r.items() if k != "feeds"})
                if now - self.last_videos >= config.VIDEO_INTERVAL:
                    log.info("videos: %s", await self.refresh_videos())
                for fid in win:
                    if now >= self.match_due.get(fid, 0):
                        self.match_due[fid] = now + config.LIVE_INTERVAL
                        m = await self.refresh_match(fid, live=True)
                        if m:
                            log.info("live %s [%s] %s %s:%s %s %s'", fid, m["source"], m["home"]["name"],
                                     m["home"]["score"], m["away"]["score"], m["away"]["name"],
                                     m["status"]["minute"] or m["status"]["state"])
                for fid in self.last_next(now):
                    if fid not in win and now >= self.match_due.get(fid, 0):
                        self.match_due[fid] = now + config.IDLE_MATCH_INTERVAL
                        m = await self.refresh_match(fid)
                        log.info("idle %s → %s", fid, m and m["source"])
                for fid in store.take_demand(self.conn, 1):
                    if not store.get(self.conn, f"match:{fid}"):
                        m = await self.refresh_match(fid)
                        log.info("demand %s → %s", fid, m and m["source"])
                # карточки игроков: заявки — всегда, плановое обновление состава — вне окна матча
                await self.tick_players(now, squad=not win)
                # очки прогнозов: после «завершён», при исправлении итога и раз в 10 мин
                await self.tick_settle(now)
                # аватары — фоновой задачей: медленный туннель не должен задерживать лайв
                if self._avatar_task is None or self._avatar_task.done():
                    self._avatar_task = asyncio.create_task(self.tick_avatars(now))
                if now >= next_state:
                    self.write_state()
                    next_state = now + 5
                    with open(config.HEARTBEAT_FILE, "w") as f:
                        f.write(str(now))
            except Exception:
                log.exception("collector: ошибка такта (продолжаю)")
            try:
                await asyncio.wait_for(stop.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
        self.write_state()


def iso_utc_date(t) -> str | None:
    return iso_utc(t)[:10] if t is not None else None


def _sofa_match(e: dict, info: dict) -> bool:
    if abs((e.get("startTimestamp") or 0) - (ts(info["kickoff"]) or 0)) > 3 * 3600:
        return False
    return same_team((e.get("homeTeam") or {}).get("name"), info["home"]) and \
        same_team((e.get("awayTeam") or {}).get("name"), info["away"])


def _ctx_from_team(team: dict) -> dict:
    names, last, dup = {}, {}, set()
    for line in (team.get("squad") or {}).values():
        for p in line:
            if not p.get("id"):
                continue
            names[name_key(p["name"])] = p["id"]
            ln = name_key(p["name"].split()[-1])
            if ln in last:
                dup.add(ln)
            last[ln] = p["id"]
    for d in dup:
        last.pop(d, None)
    return {"names": names, "last": last}


def _ctx_from_match(m: dict) -> dict:
    numbers, names, last, dup = {"home": {}, "away": {}}, {}, {}, set()
    for side in ("home", "away"):
        lu = (m.get("lineups") or {}).get(side) or {}
        for p in (lu.get("starters") or []) + (lu.get("subs") or []):
            if not p.get("id"):
                continue
            if p.get("number") is not None:
                numbers[side][str(p["number"])] = p["id"]
            names[name_key(p["name"])] = p["id"]
            ln = name_key((p["name"] or "").split()[-1])
            if ln in last:
                dup.add(ln)
            last[ln] = p["id"]
    for d in dup:
        last.pop(d, None)
    return {"numbers": numbers, "names": names, "last": last}


# ================= CLI =================

def _result_of(m: dict | None) -> tuple | None:
    """Всё, от чего зависят очки: статус, счёт, голы (минута, сторона, автор, автогол, серия)."""
    if not m:
        return None
    goals = tuple((e.get("minute"), e.get("added"), e.get("side"), (e.get("player") or {}).get("id"),
                   bool(e.get("own_goal")), bool(e.get("shootout")))
                  for e in m.get("events") or [] if e.get("type") == "goal")
    return (m["status"]["state"], m["home"].get("score"), m["away"].get("score"), goals)


def _summary(m: dict | None) -> str:
    if not m:
        return "нет данных (все источники недоступны или нет сопоставления)"
    ev = m["events"]
    st = {x["key"]: f"{x['home']}-{x['away']}" for x in (m.get("stats") or {}).get("all", [])}
    return (f"[{m['source']}] {m['home']['name']} {m['home']['score']}:{m['away']['score']} {m['away']['name']} | "
            f"state={m['status']['state']} min={m['status']['minute']}{'+' + str(m['status']['added']) if m['status']['added'] else ''} | "
            f"events={len(ev)} goals={sum(1 for e in ev if e['type'] == 'goal')} shots={len(m['shots'])} "
            f"momentum={len(m['momentum'])} | clock={m['status']['label']} poss={st.get('possession')} "
            f"shots={st.get('shots_total')} xg={st.get('xg')} | available={','.join(m['available'])}")


async def _cli(args) -> int:
    conn = store.connect()
    c = Collector(conn)
    try:
        if args.cmd == "once":
            if args.what == "team":
                print(json.dumps(await c.refresh_team(), ensure_ascii=False))
            elif args.what == "mapping":
                print(json.dumps(await c.refresh_mapping(), ensure_ascii=False))
            elif args.what == "news":
                print(json.dumps(await c.refresh_news(), ensure_ascii=False))
                c.write_state()
            elif args.what == "videos":
                print(json.dumps(await c.refresh_videos(), ensure_ascii=False))
                c.write_state()
            elif args.what == "match":
                print(_summary(await c.refresh_match(args.id)))
            elif args.what == "player":
                p = await c.refresh_player(args.id)
                print(json.dumps({k: p.get(k) for k in ("id", "name", "source", "available")} if p else None,
                                 ensure_ascii=False))
                c.write_state()
            elif args.what == "settle":
                res = await c.tick_settle(time.time(), force=True) or []
                print(json.dumps([r for r in res if r["result"] != "unchanged"], ensure_ascii=False))
            elif args.what == "avatars":
                c.last_avatars = 0.0
                print(json.dumps(await c.tick_avatars(time.time(), limit=50), ensure_ascii=False))
            elif args.what == "players":
                done = []
                while True:
                    got = await c.tick_players(time.time(), per_tick=100)
                    done += got
                    if not c.players_due(time.time()):
                        break
                    if not got:  # упёрлись в лимит минуты — ждём
                        await asyncio.sleep(5)
                print(json.dumps({"players": len(done)}, ensure_ascii=False))
                c.write_state()
        elif args.cmd == "live":
            for i in range(args.cycles):
                t0 = time.time()
                m = await c.refresh_match(args.id, live=True)
                req = {n: s.requests for n, s in c.sources.items() if s.requests}
                print(f"{datetime.now(timezone.utc):%H:%M:%S} cycle {i + 1}: {_summary(m)} | requests={req} "
                      f"| {time.time() - t0:.1f}s", flush=True)
                if i + 1 < args.cycles:
                    await asyncio.sleep(max(0, args.interval - (time.time() - t0)))
            c.write_state()
        elif args.cmd == "find-live":
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            data = await c.fm.matches_on(day)
            for lg in data.get("leagues") or []:
                for mt in lg.get("matches") or []:
                    st = mt.get("status") or {}
                    if st.get("started") and not st.get("finished"):
                        print(mt.get("id"), lg.get("name"), "|", (mt.get("home") or {}).get("name"), st.get("scoreStr"),
                              (mt.get("away") or {}).get("name"), "|", (st.get("liveTime") or {}).get("short"))
    finally:
        await c.close()
    return 0


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="python -m app.collector")
    sub = ap.add_subparsers(dest="cmd")
    o = sub.add_parser("once")
    o.add_argument("what", choices=["team", "mapping", "match", "news", "videos", "player", "players", "avatars", "settle"])
    o.add_argument("id", nargs="?")
    lv = sub.add_parser("live")
    lv.add_argument("id")
    lv.add_argument("--cycles", type=int, default=6)
    lv.add_argument("--interval", type=float, default=config.LIVE_INTERVAL)
    sub.add_parser("find-live")
    args = ap.parse_args()
    if args.cmd:
        sys.exit(asyncio.run(_cli(args)))

    async def daemon():
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        conn = store.connect()
        c = Collector(conn)
        try:
            await c.run(stop)
        finally:
            await c.close()

    asyncio.run(daemon())


if __name__ == "__main__":
    main()
