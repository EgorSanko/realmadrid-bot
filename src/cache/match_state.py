"""match_state.py — Leon-first match state resolver.

Принцип: Leon — primary source для решения is_live и core-полей матча
(home_team, away_team, score, minute, odds). FotMob — только enrichment
(incidents, lineups, momentum, shotmap, stats).

Никогда не доверяем FotMob для is_live или score — он медленно обновляется
и держит is_live=true 3-5 минут после конца матча, что вызывало баг 2026-05-11.

См. Obsidian/Real Madrid/09 - Аудит 2026-05/PRINCIPLES.md
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MatchCoreState:
    """Все поля, нужные UI для рендера. Только из Leon."""
    is_live: bool
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    minute: str
    stage: str
    kickoff_ms: Optional[int]
    bets_suspended: bool
    leon_id: Optional[str]
    live_odds: dict
    home_stats: dict
    away_stats: dict


def resolve_match_state(leon_data: Optional[dict]) -> MatchCoreState:
    """Единственная функция, решающая state матча. Только Leon."""
    if not leon_data:
        return MatchCoreState(
            is_live=False, home_team='', away_team='',
            home_score=0, away_score=0, minute='', stage='',
            kickoff_ms=None, bets_suspended=False, leon_id=None,
            live_odds={}, home_stats={}, away_stats={},
        )

    score_raw = str(leon_data.get('score') or '0:0').replace('-', ':')
    parts = score_raw.split(':')
    home_sc = int(parts[0].strip()) if parts and parts[0].strip().isdigit() else 0
    away_sc = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0

    live_status = leon_data.get('liveStatus') or {}
    stage = ''
    if isinstance(live_status, dict):
        stage = live_status.get('stage', '') or ''

    return MatchCoreState(
        is_live=bool(leon_data.get('is_live')),
        home_team=leon_data.get('home_team') or '',
        away_team=leon_data.get('away_team') or '',
        home_score=home_sc,
        away_score=away_sc,
        minute=str(leon_data.get('minute') or ''),
        stage=stage,
        kickoff_ms=leon_data.get('kickoff'),
        bets_suspended=bool(leon_data.get('bets_suspended')),
        leon_id=leon_data.get('leon_id'),
        live_odds=leon_data.get('live_odds') or {},
        home_stats=leon_data.get('home_stats') or {},
        away_stats=leon_data.get('away_stats') or {},
    )


def _teams_match(a: str, b: str) -> bool:
    a, b = (a or '').lower().strip(), (b or '').lower().strip()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def safe_fotmob_enrichment(fotmob_raw: Optional[dict], core: MatchCoreState) -> dict:
    """Безопасно извлекает enrichment-поля из FotMob.

    Никогда не меняет core. Если FotMob показывает другой матч (team mismatch)
    или null — возвращает пустые поля. UI всегда получает структуру со всеми
    ключами и никогда не падает по KeyError.
    """
    empty = {
        'incidents': [],
        'lineups': {},
        'momentum': [],
        'shotmap': [],
        'stats': {},
    }
    if not fotmob_raw or not isinstance(fotmob_raw, dict):
        return empty

    fm_home = fotmob_raw.get('home_team') or ''
    if core.home_team and not _teams_match(fm_home, core.home_team):
        # FotMob показывает другой матч (stale cache, другая команда) → игнорим
        return empty

    return {
        'incidents': fotmob_raw.get('incidents') or [],
        'lineups': fotmob_raw.get('lineups') or {},
        'momentum': fotmob_raw.get('momentum') or [],
        'shotmap': fotmob_raw.get('shotmap') or [],
        'stats': fotmob_raw.get('stats') or {},
    }


def build_live_payload(core: MatchCoreState, fotmob_raw: Optional[dict],
                       get_team_logo, build_live_markets) -> dict:
    """Собирает полный bundle['live'] / /api/live payload.

    Принимает callable-зависимости (get_team_logo, build_live_markets) чтобы
    модуль был самодостаточным и тестируемым без api.py.
    """
    payload = {
        'is_live': True,
        'home_team': core.home_team,
        'away_team': core.away_team,
        'home_score': core.home_score,
        'away_score': core.away_score,
        'score': f"{core.home_score}:{core.away_score}",
        'minute': core.minute,
        'stage': core.stage,
        'leon_id': core.leon_id,
        'bets_suspended': core.bets_suspended,
        'live_odds': core.live_odds,
        'home_logo': get_team_logo(core.home_team),
        'away_logo': get_team_logo(core.away_team),
    }

    if core.live_odds:
        payload['bet_markets'] = build_live_markets(
            core.live_odds, core.home_team, core.away_team, payload['score']
        )
    else:
        payload['bet_markets'] = []

    if core.home_stats and core.away_stats:
        payload['formatted_stats'] = [
            {'title': 'Угловые', 'home': core.home_stats.get('corners', 0),
             'away': core.away_stats.get('corners', 0)},
            {'title': 'Жёлтые карточки', 'home': core.home_stats.get('yellowCards', 0),
             'away': core.away_stats.get('yellowCards', 0)},
            {'title': 'Красные карточки', 'home': core.home_stats.get('redCards', 0),
             'away': core.away_stats.get('redCards', 0)},
        ]

    enrichment = safe_fotmob_enrichment(fotmob_raw, core)
    payload.update(enrichment)
    return payload
