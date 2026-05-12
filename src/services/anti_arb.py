"""src/services/anti_arb.py — Anti-вилка (anti-arbitrage) check.

Used by routes/bets.py to reject incoming bets/predictions that would create an
arbitrage situation with the user's existing positions on the same match.

Reasoning: each user gets one chance per match. If they bet on home + draw + away
all at full odds, they're guaranteed to win something — degenerate arbitrage.
The check covers 1X2, totals, BTTS, score X-Y, corners, cards, and double-chance
combinations.

Pure function — no state, no IO.

См. инцидент [[2026-05-04 30s вилка delay]] — anti-вилка должен включать
**и ставки, и прогнозы** в existing_bet_types.
"""


def _is_arb_against_existing(new_bet_type: str, existing_bet_types: list) -> bool:
    """Returns True if new_bet_type contradicts any existing pending bet for the same match.

    Mirrors the WebApp client-side L(e) check. Server-side enforcement so the
    public site (which lacks the inline guard) is also protected."""
    if not existing_bet_types:
        return False
    B = list(existing_bet_types)
    e = new_bet_type or ''

    # Match-result fork: home/draw/away
    has_home = 'home' in B
    has_draw = 'draw' in B
    has_away = 'away' in B
    if has_home and e in ('draw', 'away'): return True
    if has_draw and e in ('home', 'away'): return True
    if has_away and e in ('home', 'draw'): return True

    # Existing score_X-Y implies a winner side -> block opposite
    for b in B:
        if b.startswith('score_'):
            try:
                hs, as_ = b.replace('score_', '').split('-')
                hs, as_ = int(hs), int(as_)
                if hs > as_ and e in ('draw', 'away'): return True
                if hs == as_ and e in ('home', 'away'): return True
                if as_ > hs and e in ('home', 'draw'): return True
            except Exception:
                pass

    # BTTS yes/no fork
    if 'btts_yes' in B and e == 'btts_no': return True
    if 'btts_no' in B and e == 'btts_yes': return True

    # New bet is score_X-Y: check against existing winner-side bets and other scores
    if e.startswith('score_'):
        try:
            ehs, eas = e.replace('score_', '').split('-')
            ehs, eas = int(ehs), int(eas)
            if has_home and ehs <= eas: return True
            if has_draw and ehs != eas: return True
            if has_away and eas <= ehs: return True
            for b in B:
                if b.startswith('score_') and b != e:
                    try:
                        bhs, bas = b.replace('score_', '').split('-')
                        bhs, bas = int(bhs), int(bas)
                        if (bhs > bas) != (ehs > eas): return True
                        if (bhs == bas) != (ehs == eas): return True
                    except Exception:
                        pass
        except Exception:
            pass

    # Total over/under same line fork (e.g. total_over_2.5 vs total_under_2.5)
    if e.startswith('total_over_'):
        line = e.replace('total_over_', '')
        if f'total_under_{line}' in B: return True
    if e.startswith('total_under_'):
        line = e.replace('total_under_', '')
        if f'total_over_{line}' in B: return True

    # Corners over/under same line
    if e.startswith('corners_over_'):
        line = e.replace('corners_over_', '')
        if f'corners_under_{line}' in B: return True
    if e.startswith('corners_under_'):
        line = e.replace('corners_under_', '')
        if f'corners_over_{line}' in B: return True

    # Cards over/under same line
    if e.startswith('cards_over_'):
        line = e.replace('cards_over_', '')
        if f'cards_under_{line}' in B: return True
    if e.startswith('cards_under_'):
        line = e.replace('cards_under_', '')
        if f'cards_over_{line}' in B: return True

    # Double chance forks vs single outcome
    # 1X (home or draw) blocks 12 mismatches:
    if 'dc_1x' in B and e == 'away': return True
    if 'dc_x2' in B and e == 'home': return True
    if 'dc_12' in B and e == 'draw': return True
    if e == 'dc_1x' and 'away' in B: return True
    if e == 'dc_x2' and 'home' in B: return True
    if e == 'dc_12' and 'draw' in B: return True

    return False
