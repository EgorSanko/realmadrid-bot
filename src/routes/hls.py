"""src/routes/hls.py - HLS proxy + page parser.

Endpoints:
- GET /api/parse_stream - find m3u8 URLs on a page (p.a.c.k.e.r decoder + iframe walker)
- GET /api/proxy/hls    - CORS proxy for HLS playlists + segments

Helpers below are private to this group. SSRF guard via _is_safe_external_url.
get_referer_for_url stays in api.py (also used by /api/stream/proxy + /api/stream/segment).
"""
import re
import time
import requests
from urllib.parse import urljoin, quote
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api", tags=["hls"])


_PARSE_CACHE = {}  # url -> {ts, result}
_PARSE_CACHE_TTL = 300  # 5 minutes

_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

_LANG_MAP = {
    'russia': 'RU', 'ukraine': 'UA', 'england': 'EN', 'spain': 'ES',
    'france': 'FR', 'germany': 'DE', 'italy': 'IT', 'portugal': 'PT',
    'brazil': 'BR', 'turkey': 'TR', 'arab': 'AR', 'china': 'CN',
}


def _unpack_all_packer(text: str) -> list:
    """Decode ALL p.a.c.k.e.r obfuscated blocks in text, return list of decoded strings"""
    results = []
    for match in re.finditer(
        r"eval\(function\(p,a,c,k,e,[dr]\)\{.*?\}\('(.*?)',\s*(\d+),\s*(\d+),\s*'([^']+)'\.split",
        text, re.DOTALL
    ):
        p_str = match.group(1)
        a_val = int(match.group(2))
        keywords = match.group(4).split('|')

        def _base_n_decode(word, base):
            chars = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
            result = 0
            for ch in word:
                idx = chars.index(ch) if ch in chars else -1
                if idx < 0 or idx >= base:
                    return -1
                result = result * base + idx
            return result

        def _make_replacer(kw, base):
            def _replacer(m):
                word = m.group(0)
                idx = _base_n_decode(word, base)
                if 0 <= idx < len(kw) and kw[idx]:
                    return kw[idx]
                return word
            return _replacer

        decoded = re.sub(r'\b\w+\b', _make_replacer(keywords, a_val), p_str)
        decoded = decoded.replace('\\/', '/')
        results.append(decoded)
    return results


def _find_m3u8_urls(text: str) -> list:
    """Find m3u8 URLs in text"""
    urls = re.findall(r'https?://[^\s\'"<>\\]+?\.m3u8[^\s\'"<>\\]*', text)
    seen = set()
    unique = []
    for u in urls:
        u = u.rstrip('"').rstrip("'").rstrip(')').rstrip(';').rstrip(',')
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def _parse_myfootball_channels(text: str) -> list:
    """Parse myfootball.pw channel structure: section tabs + content"""
    channels = []

    # Parse channel tabs for language info
    tab_langs = {}
    for m in re.finditer(r'href="#section-(\d+)"[^>]*>(\d+)\s*<span>.*?</span>\s*(?:<img[^>]*alt="[^"]*?(\w+)")?', text, re.DOTALL):
        section_num = m.group(1)
        lang_key = m.group(3) or ''
        lang_code = _LANG_MAP.get(lang_key.lower(), '')
        tab_langs[section_num] = lang_code

    # Parse each section for m3u8 and iframes
    for m in re.finditer(r'<section\s+id="section-(\d+)">(.*?)</section>', text, re.DOTALL | re.IGNORECASE):
        section_num = m.group(1)
        section_html = m.group(2)
        lang = tab_langs.get(section_num, '')
        label = f"Канал {section_num}" + (f" [{lang}]" if lang else '')

        # Direct m3u8 in section
        m3u8s = _find_m3u8_urls(section_html)
        for u in m3u8s:
            channels.append({'url': u, 'name': label, 'type': 'direct'})

        # iframe data-src in section
        iframes = re.findall(r'<iframe[^>]+data-src=["\']([^"\']+)["\']', section_html, re.IGNORECASE)
        for iframe_url in iframes:
            if iframe_url.startswith('//'):
                iframe_url = 'https:' + iframe_url
            channels.append({'url': iframe_url, 'name': label, 'type': 'iframe'})

    return channels


def _fetch_page(url: str, referer: str = None) -> str:
    """Fetch a URL with browser-like headers, return text or empty string"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        headers = dict(_BROWSER_HEADERS)
        headers['Referer'] = referer or (origin + '/')

        resp = requests.get(url, timeout=10, headers=headers, verify=False)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"[parse_stream] Error fetching {url}: {e}")
    return ''


def _extract_m3u8_from_page(text: str, url: str) -> list:
    """Extract m3u8 URLs from page text using all methods"""
    streams = []
    seen = set()

    def add(u):
        if u not in seen:
            seen.add(u)
            streams.append(u)

    # 1. Direct m3u8 URLs
    for u in _find_m3u8_urls(text):
        add(u)

    # 2. Unpack ALL p.a.c.k.e.r blocks in full page
    for decoded in _unpack_all_packer(text):
        for u in _find_m3u8_urls(decoded):
            add(u)

    # 3. Individual script tags (for packed JS)
    script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL | re.IGNORECASE)
    for script in script_blocks:
        if 'eval(function(p,a,c,k,e,' in script:
            for decoded in _unpack_all_packer(script):
                for u in _find_m3u8_urls(decoded):
                    add(u)

    # 4. Decode atob("base64") patterns (liveball.st style)
    import base64
    atob_matches = re.findall(r'atob\(["\']([A-Za-z0-9+/=]+)["\']\)', text)
    for b64 in atob_matches:
        try:
            decoded_url = base64.b64decode(b64).decode('utf-8', errors='replace')
            for u in _find_m3u8_urls(decoded_url):
                add(u)
        except Exception:
            pass

    # 5. Fetch external JS files that look like player scripts
    from urllib.parse import urljoin as _urljoin
    js_urls = re.findall(r'<script[^>]+src=["\']([^"\']+/pll/[^"\']+)["\']', text, re.IGNORECASE)
    js_urls += re.findall(r"\.src='(/pll/[^']+)'", text)
    js_urls += re.findall(r'\.src="(/pll/[^"]+)"', text)
    # Also dynamic script creation: s.src='/pll/...'
    js_urls += re.findall(r"s\.src='([^']+/pll/[^']+)'", text)
    for js_url in js_urls:
        if not js_url.startswith('http'):
            js_url = _urljoin(url, js_url)
        js_text = _fetch_page(js_url, referer=url)
        if js_text:
            for u in _find_m3u8_urls(js_text):
                add(u)
            for decoded in _unpack_all_packer(js_text):
                for u in _find_m3u8_urls(decoded):
                    add(u)

    # Hex-encoded m3u8 (actionx.blog: const hexEncoded = "68747470...")
    for hm in re.finditer(r'''(?:hexEncoded|encodedURL|streamHex)\s*=\s*['"]([0-9a-fA-F]{40,})['"]''', text):
        try:
            decoded = bytes.fromhex(hm.group(1)).decode('utf-8', errors='replace')
            for u in _find_m3u8_urls(decoded):
                add(u)
        except Exception:
            pass
    for hm in re.finditer(r'''['"]([0-9a-fA-F]{80,})['"]''', text):
        try:
            decoded = bytes.fromhex(hm.group(1)).decode('utf-8', errors='replace')
            if 'http' in decoded and '.m3u8' in decoded:
                for u in _find_m3u8_urls(decoded):
                    add(u)
        except Exception:
            pass

    return streams



def _parse_page_for_streams(url: str, depth: int = 0, visited: set = None, referer: str = None) -> list:
    """Recursively parse page to find m3u8 stream URLs with channel info"""
    if visited is None:
        visited = set()
    if depth > 3 or url in visited:
        return []
    visited.add(url)

    results = []  # list of {url, name}

    text = _fetch_page(url, referer=referer)
    if not text:
        return []

    # Check if this is a myfootball-style page with channel tabs
    is_myfootball = 'section-1' in text and 'канал' in text.lower()

    if is_myfootball and depth == 0:
        channels = _parse_myfootball_channels(text)
        for ch in channels:
            if ch['type'] == 'direct':
                results.append({'url': ch['url'], 'name': ch['name']})
            elif ch['type'] == 'iframe':
                # Recursively parse iframe embed
                sub = _parse_page_for_streams(ch['url'], depth + 1, visited, referer=url)
                if sub:
                    for s in sub:
                        # Use channel name if sub-result has generic name
                        if s.get('name', '').startswith('Поток'):
                            s['name'] = ch['name']
                        results.append(s)
                else:
                    # Could not extract m3u8 from iframe, store as iframe fallback
                    results.append({'url': ch['url'], 'name': ch['name'], 'fallback': True})
    else:
        # Generic page: extract all m3u8
        m3u8_list = _extract_m3u8_from_page(text, url)
        for i, u in enumerate(m3u8_list):
            results.append({'url': u, 'name': f"Поток {i+1}"})

        # Follow iframes
        from urllib.parse import urljoin as _urljoin
        iframe_urls = re.findall(r'<iframe[^>]+(?:src|data-src)=["\']([^"\']+)["\']', text, re.IGNORECASE)
        for iframe_url in iframe_urls:
            if iframe_url.startswith('//'):
                iframe_url = 'https:' + iframe_url
            elif not iframe_url.startswith('http'):
                iframe_url = _urljoin(url, iframe_url)
            if any(skip in iframe_url.lower() for skip in ['google', 'facebook', 'twitter', 'ads', 'analytics', 'oleronraid', 'lernody']):
                continue
            sub = _parse_page_for_streams(iframe_url, depth + 1, visited, referer=url)
            for s in sub:
                if s['url'] not in [r['url'] for r in results]:
                    results.append(s)

    return results


def _is_safe_external_url(url: str) -> bool:
    """SSRF guard: only allow http(s) to public hostnames.
    Blocks: non-http schemes, loopback, private networks, link-local,
    cloud metadata IPs (169.254.169.254), and bare IPs in private ranges.
    """
    try:
        from urllib.parse import urlparse
        import ipaddress, socket
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False
        host = p.hostname
        if not host:
            return False
        # Resolve hostname; reject if any address is private/loopback/link-local
        try:
            infos = socket.getaddrinfo(host, None)
        except Exception:
            return False
        for info in infos:
            try:
                addr = ipaddress.ip_address(info[4][0])
            except Exception:
                return False
            if (addr.is_private or addr.is_loopback or addr.is_link_local
                    or addr.is_multicast or addr.is_reserved or addr.is_unspecified):
                return False
        return True
    except Exception:
        return False




_HLS_PROXY_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}


def _rewrite_m3u8(text: str, base_url: str) -> str:
    """Rewrite URLs in m3u8 playlist to go through proxy"""
    lines = text.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            # URL line (segment or sub-playlist)
            url = stripped
            if not url.startswith('http'):
                url = urljoin(base_url, url)
            line = '/api/proxy/hls?url=' + quote(url, safe='')
        elif 'URI="' in stripped:
            # Handle URI= attributes (#EXT-X-MAP, #EXT-X-KEY, etc.)
            def _replace_uri(match):
                uri = match.group(1)
                if not uri.startswith('http'):
                    uri = urljoin(base_url, uri)
                return 'URI="/api/proxy/hls?url=' + quote(uri, safe='') + '"'
            line = re.sub(r'URI="([^"]+)"', _replace_uri, line)
        result.append(line)
    return '\n'.join(result)





def get_referer_for_url(url: str) -> str:
    """Определяет правильный Referer для URL"""
    if 'mfvideo' in url or 'videomf' in url or 'myfootball' in url:
        return 'https://myfootball.pw/'
    elif 'liveball' in url or 'hayuhi' in url:
        return 'https://liveball4.info/'
    elif 'staypoor' in url or '58103793' in url or '77911050' in url:
        return 'https://myfootball.pw/'
    return ''

def init():
    @router.get("/parse_stream")
    def parse_stream(url: str):
        """Parse a page to find m3u8 stream URLs"""
        from fastapi.responses import JSONResponse

        if not _is_safe_external_url(url):
            raise HTTPException(status_code=400, detail="Invalid URL")

        now = time.time()
        cached = _PARSE_CACHE.get(url)
        if cached and now - cached['ts'] < _PARSE_CACHE_TTL:
            return JSONResponse(
                content=cached['result'],
                headers={'Access-Control-Allow-Origin': '*'}
            )

        streams = _parse_page_for_streams(url)

        # Filter out fallback entries for the success response
        real_streams = [s for s in streams if not s.get('fallback')]

        if real_streams:
            result = {"success": True, "streams": [{"url": s['url'], "name": s['name']} for s in real_streams]}
        else:
            result = {"success": False, "fallback_url": url}

        _PARSE_CACHE[url] = {'ts': now, 'result': result}

        return JSONResponse(
            content=result,
            headers={'Access-Control-Allow-Origin': '*'}
        )



    @router.get("/proxy/hls")
    def proxy_hls(url: str):
        """HLS proxy to bypass CORS restrictions"""
        from fastapi.responses import Response

        # Security: only proxy HLS-related URLs to public hosts (SSRF guard)
        url_lower = url.lower()
        if not any(ext in url_lower for ext in ['.m3u8', '.ts', '.m3u', '.aac', '.mp4', '.key']):
            raise HTTPException(status_code=400, detail="Only HLS URLs allowed")
        if not _is_safe_external_url(url):
            raise HTTPException(status_code=400, detail="Invalid URL")

        try:
            headers = dict(_HLS_PROXY_HEADERS)
            from urllib.parse import urlparse
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            # Use smart referer based on stream source
            smart_ref = get_referer_for_url(url)
            if smart_ref:
                headers['Referer'] = smart_ref
                headers['Origin'] = smart_ref.rstrip('/')
            else:
                headers['Referer'] = origin + '/'
                headers['Origin'] = origin

            resp = requests.get(url, timeout=10, headers=headers, verify=False)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Upstream {resp.status_code}")

            body = resp.content
            is_m3u8 = '.m3u8' in url_lower or '.m3u' in url_lower

            if is_m3u8:
                text = body.decode('utf-8', errors='replace')
                text = _rewrite_m3u8(text, url)
                body = text.encode('utf-8')
                content_type = 'application/vnd.apple.mpegurl'
                cache_control = 'no-cache, no-store'
            elif '.ts' in url_lower:
                content_type = 'video/MP2T'
                cache_control = 'public, max-age=60'
            elif '.aac' in url_lower:
                content_type = 'audio/aac'
                cache_control = 'public, max-age=60'
            elif '.key' in url_lower:
                content_type = 'application/octet-stream'
                cache_control = 'public, max-age=300'
            else:
                content_type = resp.headers.get('Content-Type', 'application/octet-stream')
                cache_control = 'public, max-age=60'

            return Response(
                content=body,
                media_type=content_type,
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, OPTIONS',
                    'Access-Control-Allow-Headers': '*',
                    'Cache-Control': cache_control,
                }
            )
        except HTTPException:
            raise
        except requests.exceptions.Timeout:
            raise HTTPException(status_code=504, detail="Upstream timeout")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Proxy error: {str(e)}")

    @router.get("/stream/proxy")
    async def stream_proxy(url: str):
        """Проксирует m3u8 стрим для обхода CORS"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Origin': 'https://myfootball.pw',
            }

            referer = get_referer_for_url(url)
            if referer:
                headers['Referer'] = referer

            response = requests.get(url, timeout=30, stream=True, headers=headers)

            content = response.content
            content_type = response.headers.get('content-type', 'application/vnd.apple.mpegurl')

            # Если это m3u8 плейлист, нужно переписать относительные URL
            if b'#EXTM3U' in content or '.m3u8' in url:
                text = content.decode('utf-8', errors='ignore')

                # Получаем базовый URL
                base_url = url.rsplit('/', 1)[0]

                # Заменяем относительные пути на абсолютные
                lines = text.split('\n')
                new_lines = []
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Это URL сегмента
                        if not line.startswith('http'):
                            line = f"{base_url}/{line}"
                    new_lines.append(line)

                content = '\n'.join(new_lines).encode('utf-8')
                content_type = 'application/vnd.apple.mpegurl'

            return StreamingResponse(
                iter([content]),
                media_type=content_type,
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache'
                }
            )
        except Exception as e:
            print(f"Stream proxy error: {e}")
            return {"error": str(e)}

    @router.get("/stream/segment")
    async def stream_segment(url: str):
        """Проксирует .ts сегменты видео"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Origin': 'https://myfootball.pw',
            }

            referer = get_referer_for_url(url)
            if referer:
                headers['Referer'] = referer

            response = requests.get(url, timeout=30, stream=True, headers=headers)

            def generate():
                for chunk in response.iter_content(chunk_size=8192):
                    yield chunk

            return StreamingResponse(
                generate(),
                media_type='video/MP2T',
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Cache-Control': 'no-cache'
                }
            )
        except Exception as e:
            print(f"Segment proxy error: {e}")
            return {"error": str(e)}

