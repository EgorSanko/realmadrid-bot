"""src/routes/match.py — Match list endpoints (upcoming + results).

Эндпоинты:
- GET /api/matches/upcoming — список предстоящих матчей (Sheets)
- GET /api/matches/results — последние результаты RM (FotMob → Sheets fallback)

Note: /api/match/details/{id}, /api/match/analytics остаются в api.py —
FotMob/ESPN coupling, перенос после Leon parser extraction.
/api/match/next извлечён 2026-05-11.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["match"])
_analytics_fn = None  # populated by init() — referenced by cache warmer


def init():
    # Helper: RuTube embed URL from football-video.org match archive.
    # Возвращает URL вида /api/embed/rutube/{id} — наш HTML-плеер с hls.js.
    def _rutube_highlight_for(home, away, date_iso):
        if not date_iso: return None
        try:
            from src.parsers.football_video import match_highlight
            url = match_highlight(home or '', away or '', date_iso)
            if url:
                import re as _re
                m = _re.search(r'rutube\.ru/(?:video|play/embed)/([a-f0-9]+)', url)
                if m: return f'/api/embed/rutube/{m.group(1)}'
        except Exception as _e:
            print(f'rutube_highlight_for err: {_e}', flush=True)
        return None


    @router.get("/matches/upcoming")
    async def get_upcoming_matches():
        from api import sheets_client, _get_team_logo
        matches = sheets_client.get_matches(limit=10) if sheets_client else []
        if not matches:
            return {"matches": []}
        result = []
        for m in matches:
            home = "Real Madrid" if m.get('is_home') else m.get('opponent')
            away = m.get('opponent') if m.get('is_home') else "Real Madrid"
            result.append({
                "id": m.get('id'),
                "home_team": home, "away_team": away,
                "home_logo": _get_team_logo(home),
                "away_logo": _get_team_logo(away),
                "date": f"{m.get('date')} {m.get('time')}",
                "competition": m.get('tournament'),
            })
        return {"matches": result}

    @router.get("/matches/results")
    async def get_match_results():
        from api import _get_fotmob_team, FOTMOB_RM_ID, _register_team, sheets_client
        try:
            team_data = _get_fotmob_team(FOTMOB_RM_ID)
            if team_data:
                fixtures = team_data.get('overview', {}).get('overviewFixtures', [])
                results = []
                # Lazy import — кеш живёт в памяти парсера, дёшево
                try:
                    from src.parsers.mysportslib import match_videos_for as _msl_match
                except Exception:
                    _msl_match = None
                for f in fixtures:
                    status = f.get('status', {})
                    if not status.get('finished'):
                        continue
                    home = f.get('home', {})
                    away = f.get('away', {})
                    match_id = f.get('id')
                    _register_team(home.get('name', ''), home.get('id'))
                    _register_team(away.get('name', ''), away.get('id'))

                    home_score = home.get('score', 0) or 0
                    away_score = away.get('score', 0) or 0
                    is_home = home.get('id') == FOTMOB_RM_ID
                    if is_home:
                        opponent = away.get('name', '')
                        gf, ga = home_score, away_score
                    else:
                        opponent = home.get('name', '')
                        gf, ga = away_score, home_score
                    result = 'win' if gf > ga else ('loss' if gf < ga else 'draw')

                    utc = status.get('utcTime', '')
                    date_str = ''
                    if utc:
                        try:
                            dt = datetime.strptime(utc[:10], '%Y-%m-%d')
                            date_str = dt.strftime('%d.%m.%Y')
                        except Exception:
                            date_str = utc[:10]

                    tournament = ''
                    if isinstance(f.get('tournament'), dict):
                        tournament = f.get('tournament', {}).get('name', '')

                    videos = []
                    # 1. mysportslib (1Т / 2Т / Полный) — заполняет videos[] первым
                    if _msl_match and utc:
                        try:
                            iso = utc[:10]
                            mv = _msl_match(home.get('name',''), away.get('name',''), iso)
                            if mv: videos = list(mv.get('videos', []))
                        except Exception as _e:
                            print(f'mysportslib match err: {_e}', flush=True)
                    # 2. football-video.org → rutube highlight — добавляется поверх
                    try:
                        from src.parsers.football_video import match_highlight as _fv_match
                        if utc:
                            rt = _fv_match(home.get('name',''), away.get('name',''), utc[:10])
                            if rt:
                                videos.append({'type': 'highlights', 'url': rt, 'provider': 'rutube'})
                    except Exception as _fve:
                        print(f'football_video highlight err: {_fve}', flush=True)


                    results.append({
                        "match_id": match_id,
                        "opponent": opponent,
                        "score": f"{home_score}:{away_score}",
                        "date": date_str,
                        "competition": tournament,
                        "is_home": is_home,
                        "result": result,
                        "home_team": home.get('name', ''),
                        "away_team": away.get('name', ''),
                        "home_score": home_score,
                        "away_score": away_score,
                        "home_logo": f"https://images.fotmob.com/image_resources/logo/teamlogo/{home.get('id','')}.png" if home.get('id') else '',
                        "away_logo": f"https://images.fotmob.com/image_resources/logo/teamlogo/{away.get('id','')}.png" if away.get('id') else '',
                        "videos": videos,
                    })
                results.reverse()
                if results:
                    return {"results": results[:10]}
            # Sheets fallback
            sheets_results = sheets_client.get_results() if sheets_client else []
            if sheets_results:
                return {"results": [{
                    "opponent": r.get('opponent', ''),
                    "score": r.get('score', ''),
                    "date": r.get('date', ''),
                    "competition": r.get('tournament', ''),
                    "is_home": r.get('is_home', True),
                    "result": r.get('result', ''),
                    "match_id": None,
                } for r in sheets_results]}
            return {"results": []}
        except Exception as e:
            print(f"Results error: {e}", flush=True)
            return {"results": []}

    @router.get("/match/next")
    async def get_next_match():
        """Получить следующий матч с коэффициентами и всеми типами ставок"""
        from api import _get_leon_cached, sheets_client, _get_team_logo, _build_live_markets, MOSCOW_TZ
        try:
            # Check for live match FIRST
            leon_live = _get_leon_cached()
            if leon_live and leon_live.get("is_live"):
                live_odds = leon_live.get("live_odds", {})

                # Ищем Sheets matchId для этого матча (чтобы расчёт ставок работал!)
                sheets_match_id = None
                try:
                    matches = sheets_client.get_matches(limit=5)
                    leon_home = leon_live.get("home_team", "")
                    leon_away = leon_live.get("away_team", "")
                    for m in (matches or []):
                        # Пробуем найти матч по командам
                        opp = m.get('opponent', '')
                        if opp and (opp in leon_home or opp in leon_away or
                                    leon_home in (opp or '') or leon_away in (opp or '')):
                            sheets_match_id = m.get('id')
                            break
                        # Или по home_team/away_team если есть
                        h = m.get('home_team', '')
                        a = m.get('away_team', '')
                        if (h and (h in leon_home or leon_home in h)) or \
                           (a and (a in leon_away or leon_away in a)):
                            sheets_match_id = m.get('id')
                            break
                except Exception as e:
                    print(f"Sheets lookup error: {e}")

                # Используем Sheets ID если нашли, иначе Leon ID
                match_id = str(sheets_match_id) if sheets_match_id else str(leon_live.get("leon_id", ""))
                print(f"Live match ID: sheets={sheets_match_id}, leon={leon_live.get('leon_id')}, using={match_id}")

                return {
                    "match": {
                        "id": match_id,
                        "leon_id": str(leon_live.get("leon_id", "")),
                        "home_team": leon_live.get("home_team", ""),
                        "away_team": leon_live.get("away_team", ""),
                        "home_logo": _get_team_logo(leon_live.get("home_team", "")),
                        "away_logo": _get_team_logo(leon_live.get("away_team", "")),
                        "date": "LIVE",
                        "competition": leon_live.get("stage", "La Liga"),
                        "is_live": True,
                        "score": leon_live.get("score", "0:0"),
                        "minute": leon_live.get("minute", ""),
                        "odds": {
                            "home": live_odds.get("home", 0),
                            "draw": live_odds.get("draw", 0),
                            "away": live_odds.get("away", 0),
                        },
                        "bet_markets": _build_live_markets(live_odds, leon_live.get("home_team", ""), leon_live.get("away_team", ""), leon_live.get("score", "0:0")),
                        "bets_suspended": leon_live.get("bets_suspended", False),
                    }
                }

            # No live match - get next from Google Sheets
            matches = sheets_client.get_matches(limit=1)
            odds = sheets_client.get_odds()

            if not matches:
                return {"match": None}

            match = matches[0]

            # Проверяем что матч ещё не начался (с запасом 5 минут)
            try:
                mt = datetime.strptime(f"{match.get('date')} {match.get('time')}", '%d.%m.%Y %H:%M')
                mt = mt.replace(tzinfo=MOSCOW_TZ)
                now = datetime.now(MOSCOW_TZ)

                if now >= mt - timedelta(minutes=5):
                    # Match started - check if live
                    leon_live = _get_leon_cached()
                    if leon_live and leon_live.get("is_live"):
                        live_odds = leon_live.get("live_odds", {})
                        # Используем Sheets match_id (уже загружен выше!)
                        return {
                            "match": {
                                "id": str(match.get('id', '')),
                                "leon_id": str(leon_live.get("leon_id", "")),
                                "home_team": leon_live.get("home_team", ""),
                                "away_team": leon_live.get("away_team", ""),
                                "home_logo": _get_team_logo(leon_live.get("home_team", "")),
                                "away_logo": _get_team_logo(leon_live.get("away_team", "")),
                                "date": "LIVE",
                                "competition": leon_live.get("stage", "La Liga"),
                                "is_live": True,
                                "score": leon_live.get("score", "0:0"),
                                "minute": leon_live.get("minute", ""),
                                "odds": {
                                    "home": live_odds.get("home", 0),
                                    "draw": live_odds.get("draw", 0),
                                    "away": live_odds.get("away", 0),
                                },
                                "bet_markets": _build_live_markets(live_odds, leon_live.get("home_team", ""), leon_live.get("away_team", ""), leon_live.get("score", "0:0")),
                                "bets_suspended": leon_live.get("bets_suspended", False),
                            }
                        }
                    else:
                        return {"match": None, "message": "Bets closed"}
            except ValueError:
                pass

            # Основные коэфы - ТОЛЬКО из Leon (двухшаговый запрос)
            sheets_opponent = match.get('opponent', '')

            # Команды ВСЕГДА берём из Sheets (Leon может вернуть другой матч!)
            if match.get('is_home'):
                sheets_home = "Real Madrid"
                sheets_away = sheets_opponent
            else:
                sheets_home = sheets_opponent
                sheets_away = "Real Madrid"

            leon_prematch = _get_leon_cached(target_opponent=sheets_opponent)

            # Проверяем что Leon вернул ПРАВИЛЬНЫЙ матч (того же соперника)
            leon_match_valid = False
            if leon_prematch and leon_prematch.get('live_odds'):
                leon_home = leon_prematch.get('home_team', '')
                leon_away = leon_prematch.get('away_team', '')
                # Используем nameDefault (английские имена) для точного сравнения
                name_default = leon_prematch.get('name_default', '')
                all_names = (leon_home + ' ' + leon_away + ' ' + name_default).lower()

                # Проверяем что соперник из Sheets есть в Leon матче
                opp_lower = sheets_opponent.lower()
                skip_words = {'real', 'madrid', 'club', 'fc', 'cf'}
                opp_words = [w for w in opp_lower.split() if len(w) > 3 and w not in skip_words]

                if opp_lower in all_names or (opp_words and any(w in all_names for w in opp_words)):
                    leon_match_valid = True
                    print(f"Prematch: Leon match VALID for '{sheets_opponent}': {leon_home} vs {leon_away} (default: {name_default})")
                else:
                    print(f"Prematch: Leon match MISMATCH! Sheets='{sheets_opponent}', Leon='{leon_home} vs {leon_away}', default='{name_default}' - ignoring")

            if leon_match_valid:
                leon_odds = leon_prematch.get('live_odds', {})
                home_odds = leon_odds.get('home', 0)
                draw_odds = leon_odds.get('draw', 0)
                away_odds = leon_odds.get('away', 0)
                bet_markets = _build_live_markets(leon_odds, sheets_home, sheets_away)
            else:
                # Leon не нашёл или вернул другой матч - показываем без кэфов
                home_odds = 0
                draw_odds = 0
                away_odds = 0
                bet_markets = []

            return {
                "match": {
                    "id": match.get('id'),
                    "home_team": sheets_home,
                    "away_team": sheets_away,
                    "home_logo": _get_team_logo(sheets_home),
                    "away_logo": _get_team_logo(sheets_away),
                    "date": f"{match.get('date')} {match.get('time')}",
                    "competition": match.get('tournament'),
                    "odds": {
                        "home": home_odds,
                        "draw": draw_odds,
                        "away": away_odds,
                    },
                    "bet_markets": bet_markets,
                    "leon_source": leon_match_valid
                }
            }
        except Exception as e:
            print(f"Error getting match: {e}")
            return {"match": None, "error": str(e)}

    @router.get("/match/analytics")
    async def get_match_analytics(nocache: bool = False):
        """Предматчевая аналитика: FotMob + Sheets fallback"""
        from api import (_time, _analytics_cache, _get_fotmob_team, _find_next_fotmob_match, _parse_fotmob_form, _get_fotmob_match, _parse_fotmob_h2h, FOTMOB_RM_ID, sheets_client)
        now = _time.time()
        cached = _analytics_cache['data']
        if not nocache and cached and not cached.get('error') and (now - _analytics_cache['time']) < _analytics_cache['ttl']:
            return cached

        try:
            # 1. Данные команды из FotMob
            team_data = _get_fotmob_team(FOTMOB_RM_ID)

            # 2. Следующий матч
            next_match = _find_next_fotmob_match(team_data) if team_data else {}
            opp_name = next_match.get('opponent', '')
            is_home = next_match.get('is_home', True)
            tournament = next_match.get('tournament', '')
            match_id = next_match.get('match_id')
            opp_id = next_match.get('opponent_id')

            # Фолбэк на Sheets если FotMob не дал следующий матч
            if not opp_name:
                try:
                    matches = sheets_client.get_matches(limit=1)
                    if matches:
                        m = matches[0]
                        opp_name = m.get('opponent', '')
                        is_home = m.get('is_home', True)
                        tournament = m.get('tournament', m.get('competition', ''))
                except:
                    pass

            if not opp_name:
                return {"error": "Матч не найден"}

            # 3. Форма Real Madrid из FotMob
            rm_form = _parse_fotmob_form(team_data) if team_data else []

            # Фолбэк на Sheets если FotMob не дал форму
            if not rm_form:
                all_results = sheets_client.get_results() or []
                for r in all_results[:10]:
                    score = r.get('score', '0:0')
                    parts = score.replace('-', ':').split(':')
                    try:
                        if r.get('is_home', True):
                            gf, ga = int(parts[0].strip()), int(parts[1].strip())
                        else:
                            ga, gf = int(parts[0].strip()), int(parts[1].strip())
                    except (ValueError, IndexError):
                        gf, ga = 0, 0
                    res_str = r.get('result', '')
                    if res_str == 'win': res = 'W'
                    elif res_str == 'loss': res = 'L'
                    elif res_str == 'draw': res = 'D'
                    elif gf > ga: res = 'W'
                    elif gf < ga: res = 'L'
                    else: res = 'D'
                    rm_form.append({
                        'opponent': r.get('opponent', ''), 'goals_for': gf, 'goals_against': ga,
                        'result': res, 'is_home': r.get('is_home', True),
                        'score': score, 'date': r.get('date', ''), 'tournament': r.get('tournament', '')
                    })

            # 4. Форма соперника из FotMob
            opp_form = []
            if opp_id:
                opp_data = _get_fotmob_team(opp_id)
                if opp_data:
                    opp_form = _parse_fotmob_form(opp_data)

            # 5. H2H из FotMob (если есть match_id) + ESPN fallback
            h2h = []
            if match_id:
                match_details = _get_fotmob_match(match_id)
                if match_details:
                    h2h = _parse_fotmob_h2h(match_details)

                # ESPN H2H fallback
                if not h2h and opp_name:
                    try:
                        import datetime as _dt
                        today = _dt.datetime.utcnow().strftime('%Y%m%d')
                        espn_id = _espn_id_cache.get(match_id, '')
                        if not espn_id:
                            h = 'Real Madrid' if is_home else opp_name
                            a = opp_name if is_home else 'Real Madrid'
                            espn_id = _espn_find_event(today, h, a)
                        if espn_id:
                            summary = _espn_get_summary(espn_id)
                            if summary:
                                for g in summary.get('headToHeadGames', [])[:10]:
                                    g_comps = g.get('competitions', [{}])[0]
                                    g_teams = g_comps.get('competitors', [])
                                    g_home = g_away = {}
                                    for gt in g_teams:
                                        if gt.get('homeAway') == 'home':
                                            g_home = gt
                                        else:
                                            g_away = gt
                                    g_date = g.get('date', '')[:10]
                                    try:
                                        d = _dt.datetime.strptime(g_date, '%Y-%m-%d')
                                        g_date = d.strftime('%d.%m.%y')
                                    except:
                                        pass
                                    h2h.append({
                                        'home_team': g_home.get('team', {}).get('displayName', ''),
                                        'away_team': g_away.get('team', {}).get('displayName', ''),
                                        'score': str(g_home.get('score', '0')) + ':' + str(g_away.get('score', '0')),
                                        'date': g_date,
                                        'tournament': ''
                                    })
                    except Exception as e:
                        print(f"ESPN H2H fallback error: {e}", flush=True)

            # 6. Статистика
            def calc_stats(form, n=5):
                f = form[:n]
                if not f: return {}
                wins = sum(1 for m in f if m['result'] == 'W')
                draws = sum(1 for m in f if m['result'] == 'D')
                losses = sum(1 for m in f if m['result'] == 'L')
                gf = sum(m['goals_for'] for m in f)
                ga = sum(m['goals_against'] for m in f)
                cnt = len(f)
                return {
                    'matches': cnt, 'wins': wins, 'draws': draws, 'losses': losses,
                    'goals_for': gf, 'goals_against': ga,
                    'avg_goals_for': round(gf / cnt, 1), 'avg_goals_against': round(ga / cnt, 1),
                    'avg_total': round((gf + ga) / cnt, 1),
                    'clean_sheets': sum(1 for m in f if m['goals_against'] == 0),
                    'btts': sum(1 for m in f if m['goals_for'] > 0 and m['goals_against'] > 0),
                }

            # 7. H2H статистика
            h2h_stats = {}
            if h2h:
                rm_w = rm_l = h2h_d = 0
                for m in h2h:
                    try:
                        s = m['score'].split(':')
                        hs, as_ = int(s[0]), int(s[1])
                        if 'Real Madrid' in m.get('home_team', ''):
                            if hs > as_: rm_w += 1
                            elif hs < as_: rm_l += 1
                            else: h2h_d += 1
                        else:
                            if as_ > hs: rm_w += 1
                            elif as_ < hs: rm_l += 1
                            else: h2h_d += 1
                    except: pass
                h2h_stats = {'rm_wins': rm_w, 'opp_wins': rm_l, 'draws': h2h_d, 'total': len(h2h)}

            # 8. Серия
            streak = ''
            if rm_form:
                first_res = rm_form[0]['result']
                count = sum(1 for m in rm_form if m['result'] == first_res)
                for i, m in enumerate(rm_form):
                    if m['result'] != first_res:
                        count = i
                        break
                label = {'W': 'побед', 'D': 'ничьих', 'L': 'поражений'}.get(first_res, '')
                if count > 1:
                    streak = f"{count} {label} подряд"

            result = {
                "opponent": opp_name,
                "is_home": is_home,
                "tournament": tournament,
                "rm_form": rm_form[:5],
                "rm_stats": calc_stats(rm_form, 5),
                "opp_form": opp_form[:5],
                "opp_stats": calc_stats(opp_form, 5),
                "streak": streak,
                "h2h": h2h[:8],
                "h2h_stats": h2h_stats,
                "source": "fotmob" if team_data else "sheets"
            }

            _analytics_cache['data'] = result
            _analytics_cache['time'] = now
            return result

        except Exception as e:
            print(f"Analytics error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    @router.get("/match/details/{match_id}")
    async def get_match_details(match_id: int):
        """Детализация матча: FotMob -> ESPN fallback -> basic fallback"""
        from api import (
            _match_details_cache, _MATCH_DETAILS_TTL_FINISHED, _MATCH_DETAILS_TTL_LIVE,
            _get_fotmob_match, _get_fotmob_team, _get_team_logo, _get_match_ratings,
            _find_youtube_highlight, _parse_fotmob_events, _parse_fotmob_lineups,
            _parse_fotmob_match_stats, _parse_fotmob_momentum, _parse_fotmob_shotmap,
            FOTMOB_API, sheets_client,
        )
        from src.parsers.espn import _espn_find_event, _espn_get_summary, _espn_parse_events, _espn_parse_lineups, _espn_parse_stats
        import time as _mt
        _now = _mt.time()
        _cached = _match_details_cache.get(match_id)
        if _cached:
            _ttl = _MATCH_DETAILS_TTL_LIVE if (_cached['data'].get('started') and not _cached['data'].get('finished')) else _MATCH_DETAILS_TTL_FINISHED
            if _now - _cached['time'] < _ttl:
                return _cached['data']
        try:
            # 1. Try FotMob first (may still work for some requests)
            md = _get_fotmob_match(match_id)
            if md:
                header = md.get('header', {})
                teams = header.get('teams', [])
                general = md.get('general', {})
                content = md.get('content', {})

                home_t = teams[0] if len(teams) > 0 else {}
                away_t = teams[1] if len(teams) > 1 else {}

                events = _parse_fotmob_events(md)
                stats = _parse_fotmob_match_stats(md)
                shotmap = _parse_fotmob_shotmap(md)
                momentum = _parse_fotmob_momentum(md)
                lineups = _parse_fotmob_lineups(md)

                # Build 'ratings' dict from lineups in ESPN-compatible schema
                # so frontend RMPlayerRatings can render it for ANY FotMob-sourced match
                # (not only the team's latest match).
                _pos_order = {'GK': 0, 'DF': 1, 'MF': 2, 'FW': 3}
                def _norm_pos(p_pos: str) -> str:
                    p_pos = (p_pos or '').upper()
                    if p_pos in ('GK',): return 'GK'
                    if any(x in p_pos for x in ('CB','LB','RB','LWB','RWB','DF','D')): return 'DF'
                    if any(x in p_pos for x in ('DM','CM','AM','LM','RM','MF','M')): return 'MF'
                    if any(x in p_pos for x in ('CF','ST','LW','RW','FW','F')): return 'FW'
                    return 'MF'
                def _to_rating_player(lp: dict) -> dict:
                    try:
                        r = float(lp.get('rating') or 0)
                    except (TypeError, ValueError):
                        r = 0.0
                    nm = lp.get('name') or ''
                    last = nm.split()[-1] if nm else ''
                    return {
                        'name': nm,
                        'lastName': last,
                        'rating': r,
                        'position': _norm_pos(lp.get('position', '')),
                        'number': lp.get('number', ''),
                        'starter': not lp.get('substitute', False),
                        'imageUrl': lp.get('image') or '',
                        'hx': lp.get('hx'),
                        'hy': lp.get('hy'),
                    }
                ratings_from_lineups = {}
                for _side in ('home','away'):
                    _plist = lineups.get(_side, []) or []
                    _out = [_to_rating_player(_p) for _p in _plist if _p.get('rating')]
                    _out.sort(key=lambda x: (0 if x['starter'] else 1, _pos_order.get(x['position'], 2)))
                    ratings_from_lineups[_side] = _out
                    ratings_from_lineups[_side + '_formation'] = lineups.get(_side + '_formation', '')
                    ratings_from_lineups[_side + '_rating'] = lineups.get(_side + '_rating', '')

                man_of_match = None
                mf = content.get('matchFacts', {})
                motm = mf.get('playerOfTheMatch', {})
                if motm:
                    man_of_match = {
                        'name': motm.get('name', {}).get('fullName', motm.get('name', '')),
                        'rating': motm.get('rating', {}).get('num', ''),
                        'team': motm.get('teamName', ''),
                    }

                highlight_url = _rutube_highlight_for(home_t.get('name',''), away_t.get('name',''), (general.get('matchTimeUTCDate') or '')[:10] if isinstance(general, dict) else None)

                _d = {
                    'match_id': match_id,
                    'home_team': home_t.get('name', ''),
                    'away_team': away_t.get('name', ''),
                    'home_score': home_t.get('score', 0) or 0,
                    'away_score': away_t.get('score', 0) or 0,
                    'home_id': home_t.get('id', ''),
                    'away_id': away_t.get('id', ''),
                    'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{home_t['id']}.png" if home_t.get('id') else '',
                    'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{away_t['id']}.png" if away_t.get('id') else '',
                    'tournament': general.get('leagueName', ''),
                    'round': general.get('leagueRoundName', ''),
                    'finished': general.get('finished', False),
                    'started': general.get('started', False),
                    'events': events,
                    'stats': stats,
                    'shotmap': shotmap,
                    'momentum': momentum,
                    'lineups': lineups,
                    'man_of_match': man_of_match,
                    'highlight_url': highlight_url,
                    'source': 'fotmob',
                    'ratings': ratings_from_lineups,
                }
                _match_details_cache[match_id] = {'data': _d, 'time': _mt.time()}
                return _d

            # 2. FotMob failed — try ESPN
            print(f"FotMob matchDetails failed for {match_id}, trying ESPN...", flush=True)

            # Chain: FotMob fixtures -> FotMob results cache -> Google Sheets
            home_name = ''
            away_name = ''
            match_date = ''
            tournament = ''
            fotmob_home_id = ''
            fotmob_away_id = ''
            sheets_score = ''

            # Step A: FotMob overviewFixtures (recent ~10 matches)
            try:
                team_data = _get_fotmob_team(FOTMOB_RM_ID)
                if team_data:
                    ovf = team_data.get('overview', {}).get('overviewFixtures', [])
                    for f in ovf:
                        if f.get('id') == match_id:
                            home_info = f.get('home', {})
                            away_info = f.get('away', {})
                            home_name = home_info.get('name', '')
                            away_name = away_info.get('name', '')
                            fotmob_home_id = home_info.get('id', '')
                            fotmob_away_id = away_info.get('id', '')
                            ts = f.get('status', {}).get('utcTime', '')
                            if ts:
                                match_date = ts[:10].replace('-', '')
                            tourn = f.get('tournament')
                            tournament = tourn.get('name', '') if isinstance(tourn, dict) else ''
                            break
            except Exception as e:
                print(f"FotMob fixtures lookup error: {e}", flush=True)

            # Step B: Google Sheets results (all past matches)
            if not home_name:
                try:
                    sheets_results = sheets_client.get_results() if sheets_client else []
                    sheets_matches = sheets_client.get_matches(limit=20) if sheets_client else []
                    all_data = (sheets_results or []) + (sheets_matches or [])
                    for sr in all_data:
                        opp = sr.get('opponent', '')
                        if not opp:
                            continue
                        is_home = sr.get('is_home', True)
                        h = 'Real Madrid' if is_home else opp
                        a = opp if is_home else 'Real Madrid'
                        date_raw = sr.get('date_raw', '') or sr.get('date', '')
                        # Normalize date to YYYYMMDD
                        dr = date_raw.replace('-', '')
                        if '.' in date_raw:
                            parts = date_raw.split('.')
                            if len(parts) == 3:
                                dr = parts[2] + parts[1] + parts[0]

                        # Try to match by searching ESPN for this match
                        # We don't have fotmob_match_id in sheets, so match by date
                        if not home_name and dr:
                            espn_test = _espn_find_event(dr, h, a)
                            if espn_test:
                                # Check if this is our match by trying to reverse-match
                                home_name = h
                                away_name = a
                                match_date = dr
                                tournament = sr.get('tournament', sr.get('competition', ''))
                                sheets_score = sr.get('score', '')
                                _espn_id_cache[match_id] = espn_test
                                print(f"Found match via Sheets: {h} vs {a} on {dr} -> ESPN {espn_test}", flush=True)
                                break
                except Exception as e:
                    print(f"Sheets lookup error: {e}", flush=True)

            if not home_name:
                return {"error": "Match not found"}

            # Find ESPN event
            espn_id = _espn_id_cache.get(match_id, '')
            if not espn_id and match_date:
                espn_id = _espn_find_event(match_date, home_name, away_name)
                if espn_id:
                    _espn_id_cache[match_id] = espn_id

            if not espn_id:
                # 3. ESPN not found — return basic data from FotMob/Sheets
                print(f"ESPN event not found for {home_name} vs {away_name}", flush=True)
                hs = as_ = 0
                if sheets_score:
                    sp = sheets_score.replace('-', ':').split(':')
                    try:
                        hs = int(sp[0].strip())
                        as_ = int(sp[1].strip())
                    except:
                        pass
                return {
                    'match_id': match_id,
                    'home_team': home_name,
                    'away_team': away_name,
                    'home_score': hs,
                    'away_score': as_,
                    'home_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png" if fotmob_home_id else _get_team_logo(home_name),
                    'away_logo': f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png" if fotmob_away_id else _get_team_logo(away_name),
                    'tournament': tournament,
                    'events': [],
                    'stats': [],
                    'lineups': {'home': [], 'away': []},
                    'source': 'sheets',
                }

            # Get ESPN summary
            summary = _espn_get_summary(espn_id)
            if not summary:
                return {"error": "ESPN data unavailable"}

            # Parse ESPN data
            h_comps = summary.get('header', {}).get('competitions', [{}])[0]
            competitors = h_comps.get('competitors', [])
            espn_home = {}
            espn_away = {}
            for c in competitors:
                if c.get('homeAway') == 'home':
                    espn_home = c
                else:
                    espn_away = c

            espn_home_team = espn_home.get('team', {})
            espn_away_team = espn_away.get('team', {})

            home_logo = ''
            away_logo = ''
            if fotmob_home_id:
                home_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_home_id}.png"
            elif espn_home_team.get('logos'):
                home_logo = espn_home_team['logos'][0].get('href', '')
            if fotmob_away_id:
                away_logo = f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_away_id}.png"
            elif espn_away_team.get('logos'):
                away_logo = espn_away_team['logos'][0].get('href', '')

            events = _espn_parse_events(summary)
            stats = _espn_parse_stats(summary)
            lineups = _espn_parse_lineups(summary)

            status = h_comps.get('status', {}).get('type', {})
            finished = status.get('completed', False)
            started = status.get('name', '') != 'STATUS_SCHEDULED'

            highlight_url = _rutube_highlight_for(home_name or espn_home_team.get('displayName',''), away_name or espn_away_team.get('displayName',''), (summary.get('header',{}).get('competitions',[{}])[0].get('date','') or '')[:10])

            # Get player ratings from FotMob
            ratings_data = {}
            if fotmob_home_id or fotmob_away_id:
                try:
                    ratings_data = _get_match_ratings(match_id, fotmob_home_id, fotmob_away_id)
                except Exception as e:
                    print(f"Ratings fetch error: {e}", flush=True)

            print(f"ESPN match details OK: {espn_id} -> {home_name} vs {away_name}, events={len(events)}, stats={len(stats)}, ratings={'yes' if ratings_data.get('home') else 'no'}", flush=True)

            _d = {
                'match_id': match_id,
                'espn_id': espn_id,
                'home_team': home_name or espn_home_team.get('displayName', ''),
                'away_team': away_name or espn_away_team.get('displayName', ''),
                'home_score': int(espn_home.get('score', 0) or 0),
                'away_score': int(espn_away.get('score', 0) or 0),
                'home_id': str(fotmob_home_id),
                'away_id': str(fotmob_away_id),
                'home_logo': home_logo,
                'away_logo': away_logo,
                'tournament': tournament or summary.get('header', {}).get('league', {}).get('name', ''),
                'finished': finished,
                'started': started,
                'events': events,
                'stats': stats,
                'shotmap': [],
                'momentum': [],
                'lineups': lineups,
                'man_of_match': None,
                'highlight_url': highlight_url,
                'source': 'espn',
                'ratings': ratings_data,
            }
            _match_details_cache[match_id] = {'data': _d, 'time': _mt.time()}
            return _d
        except Exception as e:
            print(f"Match details error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    @router.get("/highlights/rm")
    async def get_rm_highlights(force: bool = False):
        """Архив видео-обзоров матчей RM из mysportslib.blogspot.com.
        force=true триггерит refresh (тяжело, ~30s)."""
        from src.parsers.mysportslib import get_rm_videos, _videos_cache
        items = get_rm_videos(force_refresh=force)
        return {
            "count": len(items),
            "cache_age_seconds": int((__import__('time').time()) - _videos_cache.get('time', 0)),
            "items": items,
        }

    # Expose analytics function for cache warmer (pre-warms _analytics_cache every 25s)
    global _analytics_fn
    _analytics_fn = get_match_analytics
