"""src/routes/streams.py — Stream list + viewer heartbeats.

Эндпоинты (6 из 12 streams-related — простые):
- GET  /api/streams — список активных стримов
- GET  /api/stream — первый активный (legacy)
- POST /api/stream/heartbeat — keep-alive от плеера
- GET  /api/stream/heartbeat — то же через query (legacy frontend)
- GET  /api/stream/viewers — счётчик зрителей
- GET  /api/footybite/schedule — расписание матчей с трансляциями
- GET  /api/footybite/setup — резолв match_url → player_url

Не извлечено (сложный HTTP streaming, остаётся в api.py):
- /api/stream/proxy, /api/stream/segment, /api/proxy/hls (HLS прокси)
- /api/parse_stream, /api/liveball/schedule (парсеры)
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["streams"])


class _HeartbeatReq(BaseModel):
    client_id: str


def init():
    @router.get("/streams")
    async def get_streams():
        from api import get_streams_data
        data = get_streams_data()
        active = []
        for s in data.get("streams", []):
            if not s.get("active", True):
                continue
            entry = {"name": s.get("name", ""), "url": s.get("url", ""), "type": s.get("type", "hls")}
            if s.get("type") == "acestream" and s.get("ace_id"):
                entry["http_url"] = f"/ace/getstream?id={s['ace_id']}&.mp4"
            active.append(entry)
        return {"streams": active}

    @router.get("/stream")
    async def get_stream():
        from api import get_streams_data
        data = get_streams_data()
        for s in data.get("streams", []):
            if s.get("active", True) and s.get("url"):
                return {"url": s["url"], "title": s.get("name", "")}
        return {"url": "", "title": ""}

    @router.post("/stream/heartbeat")
    async def stream_heartbeat_post(req: _HeartbeatReq):
        from api import _stream_viewers, _stream_time
        if not req.client_id:
            return {"ok": False}
        _stream_viewers[req.client_id] = _stream_time.time()
        return {"ok": True}

    @router.get("/stream/heartbeat")
    async def stream_heartbeat_get(client_id: str = ""):
        from api import _stream_viewers, _stream_time
        if not client_id:
            return {"ok": False}
        _stream_viewers[client_id] = _stream_time.time()
        return {"ok": True}

    @router.get("/stream/viewers")
    async def stream_viewers():
        from api import _stream_viewers, _stream_time, _VIEWER_TTL
        now = _stream_time.time()
        stale = [cid for cid, ts in _stream_viewers.items() if now - ts > _VIEWER_TTL]
        for cid in stale:
            _stream_viewers.pop(cid, None)
        return {"count": len(_stream_viewers)}

    @router.get("/footybite/schedule")
    async def footybite_schedule():
        from api import _footybite_cache, _FOOTYBITE_TTL, _stream_time, _footybite_schedule_parse
        now = _stream_time.time()
        if _footybite_cache['data'] is not None and (now - _footybite_cache['time']) < _FOOTYBITE_TTL:
            return {"matches": _footybite_cache['data']}
        matches = _footybite_schedule_parse()
        _footybite_cache['data'] = matches
        _footybite_cache['time'] = now
        return {"matches": matches}

    @router.get("/footybite/setup")
    async def footybite_setup(match_url: str):
        import re as _re
        from api import _fb_fetch
        if not match_url or 'footybite' not in match_url:
            return {"success": False, "error": "bad url"}
        m = _re.search(r'/([A-Za-z][A-Za-z0-9-]*-vs-[A-Za-z0-9-]+)/(\d+)', match_url)
        if not m:
            return {"success": False, "error": "no slug"}
        slug, mid = m.group(1), m.group(2)
        sp_url = f'https://live.totalsportek.fyi/{slug}/{mid}'
        sp_html = _fb_fetch(sp_url)
        if sp_html:
            for im in _re.finditer(r'<iframe[^>]+src="(https?://[^"]+)"', sp_html):
                url = im.group(1)
                ul = url.lower()
                if 'youtube' in ul and 'live_chat' in ul:
                    continue
                if any(x in ul for x in ('actionx', 'embed', 'player', '.blog', 'stream')):
                    return {"success": True, "player_url": url}
        return {"success": True, "player_url": "https://actionx.blog/blog/?new=1"}
