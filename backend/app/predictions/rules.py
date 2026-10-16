"""Правила начисления очков — единственное место, где они записаны.

Прогноз — счёт матча (голы хозяев и гостей) и, по желанию, автор первого гола Реала.
Счёт берётся по итогу основного и дополнительного времени; серия пенальти не считается
(это обязанность поставщика данных: в `score` — голы без серии).

За счёт начисляется одно из (берётся лучшее совпадение):
  EXACT       — точный счёт;
  DIFF        — угадана разница мячей (в том числе ничья другим счётом: 1:1 вместо 2:2);
  OUTCOME     — угадан исход (победа хозяев / ничья / победа гостей).
Сверху и независимо от счёта:
  FIRST_SCORER — угадан автор первого гола Реала. Если Реал не забил, бонус не получает никто.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

EXACT = 5
DIFF = 3
OUTCOME = 2
FIRST_SCORER = 2

GOALS_MIN = 0
GOALS_MAX = 20


@dataclass(frozen=True)
class Points:
    score: int    # 5 / 3 / 2 / 0
    scorer: int   # 2 / 0
    exact: bool

    @property
    def total(self) -> int:
        return self.score + self.scorer

    @property
    def kind(self) -> str:
        return {EXACT: "exact", DIFF: "diff", OUTCOME: "outcome"}.get(self.score, "miss")


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def score_points(pred_home: int, pred_away: int, home: int, away: int) -> int:
    if pred_home == home and pred_away == away:
        return EXACT
    if pred_home - pred_away == home - away:
        return DIFF
    if _sign(pred_home - pred_away) == _sign(home - away):
        return OUTCOME
    return 0


def rm_goals(home: int, away: int, rm_is_home: bool) -> int:
    return home if rm_is_home else away


def scorer_points(pred_scorer: Optional[str], actual_scorer: Optional[str], real_goals: int) -> int:
    if real_goals <= 0 or pred_scorer is None or actual_scorer is None:
        return 0
    return FIRST_SCORER if str(pred_scorer) == str(actual_scorer) else 0


def compute(pred_home: int, pred_away: int, pred_scorer: Optional[str],
            home: int, away: int, actual_scorer: Optional[str], rm_is_home: bool) -> Points:
    s = score_points(pred_home, pred_away, home, away)
    b = scorer_points(pred_scorer, actual_scorer, rm_goals(home, away, rm_is_home))
    return Points(score=s, scorer=b, exact=s == EXACT)
