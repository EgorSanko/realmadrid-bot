"""src/routes/stream_proxy.py — RuTube stream extraction + HLS proxy."""
import re
import httpx
from urllib.parse import quote, urljoin, urlparse
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse


router = APIRouter(prefix="/api", tags=["stream"])

_stream_cache = {}
_STREAM_CACHE_TTL = 3600


def init():
    @router.get("/rutube-stream/{video_id}")
    async def rutube_stream(video_id: str):
        """Возвращает proxy-URL master.m3u8 (со всеми уровнями).
        Адаптивный bitrate hls.js сам выбирает уровень по реальной скорости."""
        import time as _time
        if not re.match(r'^[a-f0-9]+$', video_id):
            raise HTTPException(status_code=400, detail="Invalid video ID")

        cached = _stream_cache.get(video_id)
        if cached and (_time.time() - cached['time']) < _STREAM_CACHE_TTL:
            return cached['data']

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://rutube.ru/api/play/options/{video_id}/?no_404=true&referer=&pver=v2",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if resp.status_code != 200:
                    raise HTTPException(status_code=404, detail="Video not found")
                data = resp.json()
                master_url = data.get("video_balancer", {}).get("m3u8")
                if not master_url:
                    raise HTTPException(status_code=404, detail="No HLS stream")

                proxied = f"/api/proxy-stream?url={quote(master_url, safe='')}"
                result = {
                    "hls_url": proxied,
                    "title": data.get("title", ""),
                    "duration": data.get("duration", 0),
                    "thumbnail": data.get("thumbnail_url", ""),
                }
                _stream_cache[video_id] = {'data': result, 'time': _time.time()}
                return result
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Rutube API error: {e}")

    @router.get("/proxy-stream")
    async def proxy_stream(request: Request, url: str):
        """Проксирует HLS-плейлисты и сегменты.

        m3u8 загружаются целиком (нужно переписывать URL'ы).
        .ts сегменты streamятся chunk-by-chunk — это критично для 1080p,
        чтобы hls.js видел высокую фактическую скорость и не понижал уровень.
        """
        allowed = ['rutube.ru', 'googlevideo.com', 'youtube.com', 'bl.rutube.ru',
                   'rtbcdn.ru', 'rutubelist.ru', 'rutube.io']
        parsed = urlparse(url)
        if not any(parsed.hostname and parsed.hostname.endswith(d) for d in allowed):
            raise HTTPException(status_code=403, detail="Domain not allowed")

        is_m3u8 = url.endswith('.m3u8') or '.m3u8?' in url
        headers_up = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://rutube.ru/",
        }

        if is_m3u8:
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers_up)
                    if resp.status_code != 200:
                        raise HTTPException(status_code=resp.status_code, detail="Upstream error")
                    new_lines = []
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if line and not line.startswith('#'):
                            abs_url = urljoin(url, line)
                            new_lines.append(f"/api/proxy-stream?url={quote(abs_url, safe='')}")
                        else:
                            new_lines.append(line)
                    body = ("\n".join(new_lines)).encode('utf-8')
                    return Response(
                        content=body,
                        media_type='application/vnd.apple.mpegurl',
                        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"}
                    )
            except httpx.HTTPError as e:
                raise HTTPException(status_code=502, detail=str(e))

        async def _stream():
            # Большие chunks (256 KB) + aiter_raw — высокая throughput
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                async with client.stream("GET", url, headers=headers_up) as resp:
                    if resp.status_code != 200:
                        return
                    async for chunk in resp.aiter_raw(chunk_size=256 * 1024):
                        yield chunk

        return StreamingResponse(
            _stream(),
            media_type='video/mp2t',
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=3600",
                "X-Accel-Buffering": "no",  # nginx-hint: не буферить
            }
        )

    @router.get("/embed/rutube/{video_id}", response_class=Response)
    async def embed_rutube_player(video_id: str):
        if not re.match(r'^[a-f0-9]+$', video_id):
            raise HTTPException(status_code=400, detail="Invalid video ID")
        html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{{margin:0;padding:0;background:#000;height:100%;overflow:hidden}}
video{{width:100%;height:100%;object-fit:contain;background:#000}}
.msg{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#aaa;font:14px system-ui,sans-serif}}</style></head>
<body><div class="msg" id="msg">Загрузка...</div>
<video id="v" controls autoplay playsinline style="display:none"></video>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.13/dist/hls.min.js"></script>
<script>
fetch('/api/rutube-stream/{video_id}').then(r=>r.json()).then(d=>{{
  if(!d.hls_url) throw new Error('no hls');
  var v=document.getElementById('v');
  v.style.display='block';
  document.getElementById('msg').style.display='none';
  if(window.Hls && Hls.isSupported()){{var h=new Hls();h.loadSource(d.hls_url);h.attachMedia(v);}}
  else if(v.canPlayType('application/vnd.apple.mpegurl')){{v.src=d.hls_url;}}
  else{{document.getElementById('msg').textContent='HLS не поддерживается';v.style.display='none';document.getElementById('msg').style.display='flex';}}
}}).catch(()=>{{document.getElementById('msg').innerHTML='<a href="https://rutube.ru/video/{video_id}/" style="color:#f4d57a" target="_blank">Открыть на RuTube ↗</a>';}});
</script></body></html>"""
        return Response(content=html, media_type="text/html")
