"""Аватары: заявка при входе, скачивание сборщиком (типы, размер, хосты, редиректы), ссылка в ответах."""
import asyncio
import os
import sqlite3
import stat
from datetime import timedelta

import pytest

from app import avatars
from app.predictions import db

from .test_login import login, sign_widget

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2000
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500
PIC = "https://t.me/i/userpic/320/lm10.jpg"
CDN = "https://cdn4.telesco.pe/file/abc.jpg"


class FakeNet:
    """fetch для avatars.process: url → (status, headers, body); пишет, куда ходили."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def __call__(self, url):
        self.calls.append(url)
        r = self.routes.get(url)
        if r is None:
            raise OSError("connection refused")
        if isinstance(r, Exception):
            raise r
        return r


def ok(body=JPEG, ctype="image/jpeg", **h):
    return 200, {"content-type": ctype, "content-length": str(len(body)), **h}, body


NOW = []  # часы сервиса из фикстуры clock (заявки ставятся по ним)


def run(conn, net, **kw):
    kw.setdefault("now", NOW[0]())
    return asyncio.run(avatars.process(conn, net, **kw))


@pytest.fixture()
def conn(svc, clock):
    NOW[:] = [svc.now]
    c = db.connect(svc.db_path)
    yield c
    c.close()


def queued(conn):
    return {r[0]: r[1] for r in conn.execute("SELECT user_id, url FROM avatar_queue")}


def test_login_queues_and_collector_downloads_via_redirect(client, svc, conn, env):
    login(client, sign_widget(7, photo_url=PIC))
    assert queued(conn) == {7: PIC}
    net = FakeNet({PIC: (302, {"location": CDN}, None), CDN: ok()})
    res = run(conn, net)
    assert res == [(7, f"ok {len(JPEG)} B .jpg")] and net.calls == [PIC, CDN]
    f = env / "avatars" / "7.jpg"
    assert f.read_bytes() == JPEG
    if os.name == "posix":
        assert stat.S_IMODE(f.stat().st_mode) == 0o644  # nginx на хосте читает файл
    assert queued(conn) == {}
    url = avatars.url_for(7)
    assert url.startswith("/img/avatar/7.jpg?v=")
    # ссылка — в /api/auth/me и в строках рейтинга
    tok = login(client, sign_widget(7, photo_url=PIC)).json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Session {tok}"}).json()
    assert me["user"]["avatar"] == url
    assert queued(conn) == {}  # тот же url, файл свежий — новой заявки нет


def test_png_saved_and_old_jpg_removed(client, svc, conn, env):
    login(client, sign_widget(7, photo_url=PIC))
    run(conn, FakeNet({PIC: ok()}))
    login(client, sign_widget(7, photo_url=PIC.replace("lm10", "lm10b")))
    run(conn, FakeNet({PIC.replace("lm10", "lm10b"): ok(PNG, "image/png")}))
    assert not (env / "avatars" / "7.jpg").exists() and (env / "avatars" / "7.png").read_bytes() == PNG
    assert avatars.url_for(7).startswith("/img/avatar/7.jpg?v=")  # nginx: try_files .jpg → .png


@pytest.mark.parametrize("name,route,why", [
    ("тип gif", ok(b"GIF89a" + b"0" * 10, "image/gif"), "тип не разрешён"),
    ("тип html", ok(b"<html>", "text/html; charset=utf-8"), "тип не разрешён"),
    ("больше 1 МБ по заголовку", (200, {"content-type": "image/jpeg", "content-length": str(2 << 20)}, JPEG),
     "больше 1 МБ"),
    ("больше 1 МБ по факту", (200, {"content-type": "image/jpeg"}, JPEG + b"0" * (1 << 20)), "больше 1 МБ"),
    ("не картинка под видом jpeg", ok(b"<script>alert(1)</script>"), "не похоже на картинку"),
    ("png под видом jpeg", ok(PNG, "image/jpeg"), "не похоже на картинку"),
    ("404", (404, {}, None), "HTTP 404"),
    ("редирект на чужой хост", (302, {"location": "https://evil.example/x.jpg"}, None), "хост не разрешён"),
    ("редирект на http", (302, {"location": "http://cdn4.telesco.pe/x.jpg"}, None), "хост не разрешён"),
    ("редирект без Location", (302, {}, None), "без Location"),
])
def test_bad_responses_not_saved(client, svc, conn, env, name, route, why):
    login(client, sign_widget(7, photo_url=PIC))
    res = run(conn, FakeNet({PIC: route}))
    assert res[0][0] == 7 and res[0][1].startswith("retry") and why in res[0][1], res
    assert not (env / "avatars" / "7.jpg").exists() and avatars.url_for(7) is None


def test_redirect_loop_limited(client, svc, conn):
    login(client, sign_widget(7, photo_url=PIC))
    net = FakeNet({PIC: (302, {"location": PIC}, None)})
    res = run(conn, net)
    assert "слишком много перенаправлений" in res[0][1] and len(net.calls) == avatars.MAX_REDIRECTS + 1


def test_retry_backoff_then_give_up(client, svc, conn):
    login(client, sign_widget(7, photo_url=PIC))
    now = svc.now()
    net = FakeNet({})
    for i, pause in enumerate(avatars.RETRY_AFTER):
        res = run(conn, net, now=now)
        assert res[0][1].startswith("retry"), res
        assert run(conn, net, now=now + pause - timedelta(seconds=1)) == []  # пауза ещё не прошла
        now += pause
    assert run(conn, net, now=now)[0][1].startswith("failed")
    assert queued(conn) == {}


def test_foreign_photo_host_not_queued(client, svc, conn):
    for url in ("https://evil.example/a.jpg", "http://t.me/i/userpic/1.jpg", "https://t.me.evil.example/a.jpg",
                "https://user:pw@t.me/a.jpg", "javascript:alert(1)"):
        login(client, sign_widget(7, photo_url=url))
        assert queued(conn) == {}, url


def test_photo_removed_deletes_file(client, svc, conn, env):
    login(client, sign_widget(7, photo_url=PIC))
    run(conn, FakeNet({PIC: ok()}))
    login(client, sign_widget(7))  # фото скрыто
    assert queued(conn) == {7: None}
    assert run(conn, FakeNet({})) == [(7, "removed")]
    assert not (env / "avatars" / "7.jpg").exists() and avatars.url_for(7) is None
    login(client, sign_widget(7))
    assert queued(conn) == {}  # нечего ни качать, ни удалять


def test_requeue_throttled_and_refresh_weekly(svc, conn, env, client):
    login(client, sign_widget(7, photo_url=PIC))
    c = sqlite3.connect(svc.db_path)
    first = c.execute("SELECT asked_at FROM avatar_queue").fetchone()[0]
    login(client, sign_widget(7, photo_url=PIC))
    assert c.execute("SELECT asked_at FROM avatar_queue").fetchone()[0] == first  # не чаще раза в 10 мин
    c.close()
    run(conn, FakeNet({PIC: ok()}))
    later = svc.now() + avatars.REFRESH_AFTER + timedelta(minutes=1)
    assert avatars.want(conn, 7, PIC, later) is True  # раз в неделю — обновить


def test_queue_for_unknown_user_ignored(svc, conn):
    assert avatars.want(conn, 999, PIC) is False


def test_allowed_hosts():
    assert avatars.allowed_url("https://t.me/i/userpic/320/x.jpg")
    assert avatars.allowed_url("https://cdn4.telesco.pe/file/x.jpg")
    assert avatars.allowed_url("https://cdn5.cdn-telegram.org/file/x.jpg")
    assert not avatars.allowed_url("https://t.me:8443/x.jpg")
    assert not avatars.allowed_url("https://nott.me/x.jpg")
    assert not avatars.allowed_url(None)


def test_collector_tick_uses_queue(client, svc, clock, env):
    """Сборщик: такт берёт заявку из predictions.db и пишет файл (fetch подменён)."""
    import time
    from datetime import datetime, timezone

    from app.collector import Collector

    clock.set(datetime.now(timezone.utc))
    login(client, sign_widget(7, photo_url=PIC))
    col = Collector.__new__(Collector)  # без HTTP-клиентов источников
    col.last_avatars, col.cycles, col._avatar_close = 0.0, {}, None
    col._avatar_fetch = FakeNet({PIC: ok()})
    assert asyncio.run(col.tick_avatars(time.time())) == [(7, f"ok {len(JPEG)} B .jpg")]
    assert asyncio.run(col.tick_avatars(time.time())) == []  # пауза AVATAR_INTERVAL
    assert (env / "avatars" / "7.jpg").exists() and col.cycles["avatars"] == 1


def test_curl_fetch_streams_and_caps_size():
    """Настоящий curl_cffi против локального сервера: заголовки, тело, обрезка после 1 МБ, без редиректов."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redir":
                self.send_response(302)
                self.send_header("Location", "/a.jpg")
                self.end_headers()
                return
            body = JPEG if self.path == "/a.jpg" else JPEG * 1600
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    async def go():
        fetch, close = avatars.curl_fetch("", timeout=5)
        try:
            a = await fetch(base + "/a.jpg")
            r = await fetch(base + "/redir")
            big = await fetch(base + "/big.jpg")
        finally:
            await close()
        return a, r, big

    try:
        a, r, big = asyncio.run(go())
    finally:
        srv.shutdown()
    assert a[0] == 200 and a[1]["content-type"] == "image/jpeg" and a[2] == JPEG
    assert r[0] == 302 and r[1]["location"] == "/a.jpg" and r[2] is None
    assert big[0] == 200 and avatars.MAX_BYTES < len(big[2]) <= avatars.MAX_BYTES + (1 << 17)
