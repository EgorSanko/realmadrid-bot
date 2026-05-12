"""src/parsers/youtube.py — Highlight finder from RM official YouTube channel.

"""
import time as _time
import requests


_yt_cache = {}  # {opponent: {url, time}}

def _find_youtube_highlight(home_team: str, away_team: str, date_iso: str = None, score: str = None) -> str:
    """Find actual YouTube highlight video from RM official channel.
    date_iso: optional 'YYYY-MM-DD' — уточняет поиск, чтобы не вернуть видео
    другого матча против той же команды."""
    try:
        import urllib.parse, re

        rm_aliases = ['real madrid', 'real', 'madrid']
        if any(a in home_team.lower() for a in rm_aliases):
            opponent = away_team
        else:
            opponent = home_team
        opponent = opponent.strip()
        if not opponent:
            return None

        # Cache key учитывает дату — иначе для двух матчей с тем же
        # соперником мы будем возвращать один и тот же highlight.
        cache_key = f"{opponent.lower()}|{date_iso or ''}"
        cached = _yt_cache.get(cache_key)
        if cached and (_time.time() - cached['time']) < 3600:
            return cached['url']

        # Query: добавляем дату если есть. RM в названии highlight-видео
        # часто указывает 'Highlights | Real Madrid X-Y Opponent | LaLiga 25/26'.
        # Поэтому ищем через 'opponent highlights' + год.
        query = f"{opponent} highlights"
        if date_iso and len(date_iso) >= 7:
            year = date_iso[:4]
            month = int(date_iso[5:7])
            ru_months = ['', 'enero', 'february', 'march', 'april', 'may', 'june',
                         'july', 'august', 'september', 'october', 'november', 'december']
            query = f"{opponent} highlights {year}"
        # &sp=CAI%253D — сортировка по дате загрузки (Newest first), чтобы получить актуальный highlight
        search_url = f"https://www.youtube.com/@realmadrid/search?query={urllib.parse.quote(query)}&sp=CAI%253D"
        r = requests.get(search_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })

        if r.status_code != 200:
            print(f"YouTube search: status={r.status_code}", flush=True)
            _yt_cache[cache_key] = {'url': search_url, 'time': _time.time()}
            return search_url

        # Extract pairs (videoId, title) — title нужен для верификации матча.
        # Структура YouTube JSON: "videoId":"xxx"..."text":"Title"  (title ближайший)
        candidates = []
        html_window = r.text
        for m in re.finditer(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', html_window):
            vid = m.group(1)
            # Ищем ближайший text после videoId, в пределах ~3000 chars
            window = html_window[m.end():m.end()+3000]
            t = re.search(r'"text"\s*:\s*"([^"]{10,150})"', window)
            if t: candidates.append((vid, t.group(1)))

        # Парсим счёт матча в форматах '2:0' или '2-0', чтобы найти точно тот матч
        score_pairs = []
        if score:
            m_sc = re.search(r'(\d+)\s*[:\-]\s*(\d+)', score)
            if m_sc:
                a, b = m_sc.group(1), m_sc.group(2)
                # YouTube ставит счёт в любом порядке: home-away ИЛИ away-home
                score_pairs = [(a, b), (b, a)]

        def _is_match_video(title: str) -> bool:
            tl = title.lower()
            if 'highlights' not in tl: return False
            if opponent.lower().split()[0] not in tl: return False
            # Если знаем счёт — title должен содержать ровно эту цифровую пару
            if score_pairs:
                ok = False
                for h, a in score_pairs:
                    if re.search(rf'{h}\s*[\-:]\s*{a}', title): ok = True
                if not ok: return False
            return True

        chosen_id = None
        chosen_title = None
        seen = set()
        for vid, title in candidates:
            if vid in seen: continue
            seen.add(vid)
            if _is_match_video(title):
                chosen_id = vid
                chosen_title = title
                break

        if chosen_id:
            video_url = f"https://www.youtube.com/watch?v={chosen_id}"
            print(f"YouTube highlight for {opponent} ({date_iso or 'no-date'}): {chosen_title} → {video_url}", flush=True)
            _yt_cache[cache_key] = {'url': video_url, 'time': _time.time()}
            return video_url

        print(f"YouTube: no matching highlight for {opponent} ({date_iso or 'no-date'})", flush=True)
        _yt_cache[cache_key] = {'url': None, 'time': _time.time()}
        return None

    except Exception as e:
        print(f"YouTube highlight error: {e}", flush=True)
        return None
