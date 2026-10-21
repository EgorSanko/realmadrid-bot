"""Запись эфира и ролики голов.

Пока в DATA_DIR/stream.json эфир включён, ffmpeg пишет поток кусками по 4 с без перекодирования и без звука
в DATA_DIR/rec/<номер>.ts; время куска — время записи файла (mtime). Имя по времени не годится:
ffmpeg получает эфир пачками по 5 с и режет их мгновенно, два куска в одну секунду затирали друг друга
(терялась пятая часть эфира). Номера начинаются с unix-времени запуска — после перезапуска не повторяются. Хранятся последние REC_KEEP секунд, старое стирается.
Сборщик кладёт снимки идущего матча в rm.sqlite3 — новый гол в них (или ручной запрос) ставит ролик
в очередь: окно [момент обнаружения − CLIP_BEFORE, + CLIP_AFTER], склейка тех же кусков в mp4
(без перекодирования) после того, как окно дописалось. Рядом с mp4 — .json: кто, минута, счёт, матч.

FotMob сообщает о голе позже, чем он случился, а эфир отстаёт от жизни, поэтому окно берётся
с запасом в обе стороны — подрезать точнее владелец может сам.

  python -m app.recorder                # служба (контейнер rm-v2-recorder)
  python -m app.recorder clip [подпись] # ролик «сейчас» — как будто только что забили (для проверки)

Только stdlib: в образе нужен лишь ffmpeg.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("recorder")

DATA = Path(os.environ.get("DATA_DIR", "/data"))
REC = DATA / "rec"
CLIPS = DATA / "clips"
REQUESTS = CLIPS / "requests"

SEGMENT = 4                                              # длина куска, с
REC_KEEP = int(os.environ.get("REC_KEEP", "600"))        # сколько эфира держать на диске, с
CLIP_BEFORE = int(os.environ.get("CLIP_BEFORE", "180"))  # до обнаружения: FotMob узнаёт о голе через ~2 мин (21.10 гол 43:08 → 45:30)
CLIP_AFTER = int(os.environ.get("CLIP_AFTER", "60"))     # после, с (итого 4 мин — владелец сам обрезает)
CLIP_KEEP_DAYS = int(os.environ.get("CLIP_KEEP_DAYS", "14"))
GOALS_EVERY = 5                                          # как часто смотреть снимки матчей, с


def _now() -> float:
    return time.time()


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s or "", flags=re.UNICODE).strip()
    return re.sub(r"\s+", "_", s)[:60] or "x"


# ---------- эфир ----------

def _stream_url() -> str | None:
    try:
        st = json.loads((DATA / "stream.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = st.get("url") if isinstance(st, dict) else None
    return url if st.get("live") and isinstance(url, str) and url else None


class Recorder:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.url: str | None = None
        self.retry_at = 0.0

    def tick(self, url: str | None) -> None:
        if self.proc and self.proc.poll() is not None:
            log.warning("ffmpeg вышел (код %s) — перезапуск", self.proc.returncode)
            self.proc, self.retry_at = None, _now() + 3
        if url != self.url and self.proc:
            self.stop()
        self.url = url
        if url and not self.proc and _now() >= self.retry_at:
            REC.mkdir(parents=True, exist_ok=True)
            self.proc = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                 "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
                 "-rw_timeout", "15000000", "-i", url,
                 "-map", "0:v:0", "-an", "-c", "copy",   # без звука — так попросил владелец
                 "-f", "segment", "-segment_time", str(SEGMENT), "-reset_timestamps", "1",
                 "-segment_start_number", str(int(_now())), str(REC / "%d.ts")])
            log.info("запись эфира: старт")

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            log.info("запись эфира: стоп")
        self.proc = None


def _segments() -> list[tuple[float, Path]]:
    """(время окончания записи, файл) по порядку номеров."""
    out = []
    for p in REC.glob("*.ts"):
        if p.stem.isdigit():
            try:
                out.append((int(p.stem), p.stat().st_mtime, p))
            except OSError:
                pass
    return [(t, p) for _, t, p in sorted(out)]


def _prune(now: float) -> None:
    for t, p in _segments()[:-1]:          # последний кусок ещё пишется
        if t < now - REC_KEEP:
            p.unlink(missing_ok=True)
    for p in CLIPS.glob("*.*"):
        if p.is_file() and p.stat().st_mtime < now - CLIP_KEEP_DAYS * 86400:
            p.unlink(missing_ok=True)


# ---------- голы ----------

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DATA / 'rm.sqlite3'}?mode=ro", uri=True, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _snap(conn, key: str):
    row = conn.execute("SELECT data FROM snapshots WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _live_matches(conn) -> list[dict]:
    out = []
    for f in _snap(conn, "fixtures") or []:
        if (f.get("status") or {}).get("live") and f.get("id") is not None:
            m = _snap(conn, f"match:{f['id']}")
            if m:
                out.append(m)
    return out


def _goal_key(e: dict, goals: list[dict]) -> tuple:
    """Гол = счёт после него. Автор (и иногда минута) приходят через ~30 с после самого гола —
    по ним тот же гол выглядел бы новым и давал второй ролик. Нет счёта — номер гола этой стороны."""
    sc = e.get("score")
    if isinstance(sc, (list, tuple)) and len(sc) == 2 and None not in sc:
        return tuple(sc)
    side = e.get("side")
    return (side, sum(1 for g in goals[:goals.index(e) + 1] if g.get("side") == side))


class Goals:
    """Новые голы идущих матчей. Голы, которые уже были при первом взгляде на матч, роликов не дают."""

    def __init__(self):
        self.seen: dict[str, set] = {}
        self.score: dict[str, tuple] = {}

    def poll(self) -> list[dict]:
        try:
            conn = _db()
        except sqlite3.Error as e:
            log.warning("база: %s", e)
            return []
        try:
            matches = _live_matches(conn)
        except (sqlite3.Error, ValueError) as e:
            log.warning("снимки: %s", e)
            return []
        finally:
            conn.close()
        new = []
        for m in matches:
            mid = str(m.get("id"))
            goals = [e for e in m.get("events") or [] if e.get("type") == "goal" and not e.get("shootout")]
            keys = {_goal_key(e, goals) for e in goals}
            score = (m.get("home") or {}).get("score"), (m.get("away") or {}).get("score")
            score = score if None not in score else None
            if mid not in self.seen:
                self.seen[mid] = keys | ({score} if score else set())
                if score:
                    self.score[mid] = score
                continue
            for e in goals:
                k = _goal_key(e, goals)
                if k not in self.seen[mid]:
                    new.append(_goal_meta(m, e))
                    self.seen[mid].add(k)
            # FotMob бывает отдаёт счёт, а событий голов нет совсем (Реал — Лейпциг 21.10: events пусты весь тайм) —
            # новый счёт сам по себе гол; автора подтянет _refresh, если события появятся к нарезке
            if score and sum(score) and score not in self.seen[mid]:
                new.append(_score_meta(m, score, self.score.get(mid)))
                self.seen[mid].add(score)
            if score:
                self.score[mid] = score
        return new


def _refresh(job: dict) -> dict:
    """К моменту нарезки (через ~минуту) автор гола обычно уже известен — берём свежие данные."""
    if not job.get("match_id") or not job.get("score"):
        return job
    try:
        conn = _db()
        try:
            m = _snap(conn, f"match:{job['match_id']}")
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
        return job
    goals = [e for e in (m or {}).get("events") or [] if e.get("type") == "goal" and not e.get("shootout")]
    for e in goals:
        if list(_goal_key(e, goals)) == list(job["score"]):
            return {**job, **_goal_meta(m, e)}
    return job


def _score_meta(m: dict, score: tuple, prev: tuple | None) -> dict:
    st = m.get("status") or {}
    goals = [e for e in m.get("events") or [] if e.get("type") == "goal" and not e.get("shootout")]
    for e in goals:   # событие с этим счётом уже есть — берём его
        if list(_goal_key(e, goals)) == list(score):
            return _goal_meta(m, e)
    side = "home" if prev is None or score[0] > prev[0] else "away"
    home, away = m.get("home") or {}, m.get("away") or {}
    minute = f"{st.get('minute') or ''}" + (f"+{st['added']}" if st.get("added") else "")
    return {"match_id": m.get("id"), "home": home.get("name"), "away": away.get("name"), "goal_key": None,
            "minute": minute, "side": side, "player": "", "own_goal": False, "penalty": False,
            "score": list(score), "label": f"{minute}' {score[0]}-{score[1]}"}


def _goal_meta(m: dict, e: dict) -> dict:
    home, away = m.get("home") or {}, m.get("away") or {}
    minute = f"{e.get('minute')}" + (f"+{e['added']}" if e.get("added") else "")
    score = e.get("score") or [home.get("score"), away.get("score")]
    pl = e.get("player") or {}
    player = pl.get("name") or ""
    return {
        "match_id": m.get("id"), "home": home.get("name"), "away": away.get("name"),
        # ключ карточки в «Мадридиста · Клипы» (goalpick.goal_identity); клипы ищут карточку и по счёту —
        # ключ меняется, когда приходит автор
        "goal_key": f"{m.get('id')}:{e.get('side')}:{e.get('minute')}:{e.get('added') or 0}:{pl.get('id') or pl.get('name')}",
        "minute": minute, "side": e.get("side"), "player": player,
        "own_goal": bool(e.get("own_goal")), "penalty": bool(e.get("penalty")), "score": score,
        "label": f"{minute}' {player}".strip(),
        # на сколько минут матча FotMob опоздал с голом (21.10: гол 52′ пришёл на 55-й) — окно ролика сдвигаем назад
        "lag_min": max(0, ((m.get("status") or {}).get("minute") or 0) - (e.get("minute") or 0)),
    }


# ---------- ролики ----------

def _request(label: str) -> None:
    """Ручной ролик: файл-заявка, служба подхватит его в течение пары секунд."""
    REQUESTS.mkdir(parents=True, exist_ok=True)
    p = REQUESTS / f"{int(_now() * 1000)}.json"
    p.write_text(json.dumps({"label": label, "manual": True}, ensure_ascii=False), encoding="utf-8")
    print(f"заявка принята: ролик будет через ~{CLIP_AFTER + SEGMENT * 2} с в {CLIPS}")


def _take_requests() -> list[dict]:
    out = []
    for p in sorted(REQUESTS.glob("*.json")):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
            meta["at"] = int(p.stem) / 1000
            out.append(meta)
        except (OSError, ValueError):
            pass
        p.unlink(missing_ok=True)
    return out


def _cut(job: dict) -> Path | None:
    job = _refresh(job)
    start, end = job["at"] - CLIP_BEFORE, job["at"] + CLIP_AFTER
    parts = [p for t, p in _segments()[:-1] if start <= t <= end + 2 * SEGMENT]  # t — конец куска; последний ещё пишется
    if not parts:
        log.warning("ролик %s: в буфере нет эфира за это время", job.get("label"))
        return None
    stamp = datetime.fromtimestamp(job["at"], timezone.utc).strftime("%Y%m%d-%H%M%S")
    teams = f"{job['home']}-{job['away']}" if job.get("home") else "efir"
    name = f"{stamp}_{_slug(teams)}_{_slug(job.get('label') or 'gol')}"
    CLIPS.mkdir(parents=True, exist_ok=True)
    lst = CLIPS / f".{name}.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    out, tmp = CLIPS / f"{name}.mp4", CLIPS / f".{name}.mp4"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                        "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", "-an", "-movflags", "+faststart", str(tmp)],
                       capture_output=True, text=True, timeout=120)
    lst.unlink(missing_ok=True)
    if r.returncode or not tmp.exists():
        log.error("ролик %s: ffmpeg %s — %s", name, r.returncode, r.stderr[-300:])
        tmp.unlink(missing_ok=True)
        return None
    os.replace(tmp, out)
    meta = {**job, "file": out.name, "from": start, "to": end, "segments": len(parts),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("ролик готов: %s (%d кусков)", out.name, len(parts))
    return out


def run() -> None:
    rec, goals, jobs = Recorder(), Goals(), []
    next_goals = 0.0
    log.info("старт: буфер %d с, окно ролика −%d/+%d с", REC_KEEP, CLIP_BEFORE, CLIP_AFTER)
    try:
        while True:
            now = _now()
            rec.tick(_stream_url())
            if now >= next_goals:
                next_goals = now + GOALS_EVERY
                for g in goals.poll():
                    shift = max(0, (g.get("lag_min") or 0) - 1) * 60
                    log.info("гол: %s — ролик в очереди (опоздание %s мин, окно раньше на %d с)",
                             g["label"], g.get("lag_min"), shift)
                    jobs.append({**g, "at": now - shift, "detected": now})
            jobs += _take_requests()
            ready = [j for j in jobs if now >= j["at"] + CLIP_AFTER + SEGMENT * 2]
            for j in ready:
                jobs.remove(j)
                try:
                    _cut(j)
                except Exception:  # noqa: BLE001 — один сломанный ролик не должен ронять запись
                    log.exception("ролик %s", j.get("label"))
            _prune(now)
            time.sleep(2)
    finally:
        rec.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "clip":
        _request(" ".join(sys.argv[2:]) or "test")
    else:
        run()
