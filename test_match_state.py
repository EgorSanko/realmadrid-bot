"""Tests for match_state.py — Leon-first match resolver.

Запуск на VPS:
  docker exec rm-api python -m pytest /app/test_match_state.py -v
"""
import sys
sys.path.insert(0, '/app')

from match_state import (
    MatchCoreState,
    resolve_match_state,
    safe_fotmob_enrichment,
    build_live_payload,
    _teams_match,
)


# === resolve_match_state — только Leon ===

def test_no_data():
    s = resolve_match_state(None)
    assert s.is_live is False
    assert s.home_team == ''
    assert s.live_odds == {}


def test_empty_dict():
    s = resolve_match_state({})
    assert s.is_live is False
    assert s.home_score == 0


def test_leon_live_full():
    s = resolve_match_state({
        'is_live': True, 'home_team': 'Real Madrid', 'away_team': 'Barcelona',
        'score': '2:1', 'minute': '67', 'bets_suspended': False, 'leon_id': '12345',
        'live_odds': {'home': 1.5}, 'liveStatus': {'stage': 'second_half'},
    })
    assert s.is_live is True
    assert s.home_score == 2
    assert s.away_score == 1
    assert s.minute == '67'
    assert s.stage == 'second_half'
    assert s.leon_id == '12345'


def test_leon_prematch():
    s = resolve_match_state({
        'is_live': False, 'home_team': 'Real Madrid', 'away_team': 'Real Oviedo',
        'kickoff': 1778787000000,
    })
    assert s.is_live is False
    assert s.kickoff_ms == 1778787000000


def test_score_with_dash():
    s = resolve_match_state({'is_live': True, 'home_team': 'X', 'away_team': 'Y', 'score': '3-1'})
    assert s.home_score == 3
    assert s.away_score == 1


def test_score_malformed():
    s = resolve_match_state({'is_live': True, 'home_team': 'X', 'away_team': 'Y', 'score': 'abc'})
    assert s.home_score == 0
    assert s.away_score == 0


# === _teams_match ===

def test_teams_exact():
    assert _teams_match('Real Madrid', 'Real Madrid')


def test_teams_substring():
    assert _teams_match('Real Madrid', 'Real Madrid CF')


def test_teams_different():
    assert not _teams_match('Barcelona', 'Real Oviedo')


def test_teams_empty():
    assert not _teams_match('', 'Real Madrid')
    assert not _teams_match('Real Madrid', '')


# === safe_fotmob_enrichment ===

def test_enrichment_none_fotmob():
    core = resolve_match_state({'is_live': True, 'home_team': 'Real Madrid', 'away_team': 'Barcelona'})
    e = safe_fotmob_enrichment(None, core)
    assert e['incidents'] == []
    assert e['lineups'] == {}


def test_enrichment_team_mismatch():
    """FotMob показывает Барселону-Реал, а Leon уже на следующий матч с Овьедо.
    Это симуляция бага 2026-05-11.
    """
    core = resolve_match_state({'is_live': True, 'home_team': 'Real Madrid', 'away_team': 'Real Oviedo'})
    stale_fotmob = {
        'home_team': 'Barcelona', 'away_team': 'Real Madrid',
        'incidents': [{'goal': True}],
        'lineups': {'home': ['Lamine Yamal']},
    }
    e = safe_fotmob_enrichment(stale_fotmob, core)
    assert e['incidents'] == []  # stale data выкинуто
    assert e['lineups'] == {}


def test_enrichment_teams_match():
    core = resolve_match_state({'is_live': True, 'home_team': 'Real Madrid', 'away_team': 'Barcelona'})
    valid_fotmob = {
        'home_team': 'Real Madrid', 'away_team': 'Barcelona',
        'incidents': [{'goal': True, 'minute': 23}],
        'lineups': {'home': ['Bellingham'], 'away': []},
        'momentum': [1, 2, 3],
        'shotmap': [{'x': 50, 'y': 60}],
        'stats': {'possession': 55},
    }
    e = safe_fotmob_enrichment(valid_fotmob, core)
    assert len(e['incidents']) == 1
    assert e['lineups']['home'] == ['Bellingham']
    assert e['momentum'] == [1, 2, 3]
    assert e['stats']['possession'] == 55


# === build_live_payload ===

def test_payload_no_fotmob():
    """КРИТИЧЕСКИЙ ТЕСТ: bundle.live работает даже без FotMob."""
    core = resolve_match_state({
        'is_live': True, 'home_team': 'Real Madrid', 'away_team': 'Barcelona',
        'score': '2:1', 'minute': '67', 'live_odds': {'home': 1.5},
        'leon_id': 'X',
    })
    payload = build_live_payload(
        core,
        fotmob_raw=None,
        get_team_logo=lambda t: f'logo-{t}',
        build_live_markets=lambda odds, h, a, s: [{'market': 'WDW'}],
    )
    assert payload['is_live'] is True
    assert payload['score'] == '2:1'
    assert payload['home_team'] == 'Real Madrid'
    assert payload['home_logo'] == 'logo-Real Madrid'
    assert payload['bet_markets'] == [{'market': 'WDW'}]
    # Enrichment поля присутствуют как пустые
    assert payload['incidents'] == []
    assert payload['lineups'] == {}


def test_payload_with_fotmob():
    core = resolve_match_state({
        'is_live': True, 'home_team': 'Real Madrid', 'away_team': 'Barcelona',
        'score': '2:1', 'live_odds': {'home': 1.5},
    })
    fotmob = {
        'home_team': 'Real Madrid', 'away_team': 'Barcelona',
        'incidents': [{'goal': True}],
        'lineups': {'home': ['Player1']},
    }
    payload = build_live_payload(
        core, fotmob_raw=fotmob,
        get_team_logo=lambda t: '',
        build_live_markets=lambda *a: [],
    )
    assert payload['incidents'] == [{'goal': True}]
    assert payload['lineups']['home'] == ['Player1']
    # Score всё равно из Leon, не из FotMob
    assert payload['score'] == '2:1'


# === Регрессия 2026-05-11 ===

def test_regression_fotmob_says_live_leon_says_done():
    """Симуляция бага 2026-05-11: FotMob держит is_live=true, Leon уже false.
    Решение всегда из Leon → is_live=False."""
    leon = {'is_live': False, 'home_team': '', 'away_team': ''}
    core = resolve_match_state(leon)
    assert core.is_live is False
    # И даже если бы мы зашли в build_live_payload, FotMob не повлияет на core


def test_regression_old_match_in_fotmob():
    """FotMob показывает закончившийся Барселона-Реал, Leon уже на следующий матч.
    Enrichment отвергается из-за team mismatch."""
    leon = {
        'is_live': True, 'home_team': 'Real Madrid', 'away_team': 'Real Oviedo',
        'score': '0:0', 'live_odds': {'home': 1.2},
    }
    fotmob_stale = {
        'is_live': True, 'home_team': 'Barcelona', 'away_team': 'Real Madrid',
        'incidents': [{'minute': 90, 'goal': True}],
        'home_score': 2, 'away_score': 0,
    }
    core = resolve_match_state(leon)
    payload = build_live_payload(
        core, fotmob_raw=fotmob_stale,
        get_team_logo=lambda t: '',
        build_live_markets=lambda *a: [],
    )
    assert payload['home_team'] == 'Real Madrid'  # не Barcelona
    assert payload['score'] == '0:0'              # из Leon, не 2:0
    assert payload['incidents'] == []             # stale enrichment выкинут
