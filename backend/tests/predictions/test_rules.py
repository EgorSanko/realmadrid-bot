import pytest

from app.predictions import rules
from app.predictions.rules import DIFF, EXACT, FIRST_SCORER, OUTCOME, compute

# (случай, прогноз h:a, бомбардир прогноза, факт h:a, бомбардир факта, Реал дома, очки за счёт, бонус)
CASES = [
    ("точный, победа хозяев", (2, 1), None, (2, 1), None, True, EXACT, 0),
    ("точный, ничья 0:0", (0, 0), None, (0, 0), None, True, EXACT, 0),
    ("разница, победа", (3, 2), None, (2, 1), None, True, DIFF, 0),
    ("разница, ничья другим счётом 1:1 вместо 2:2", (1, 1), None, (2, 2), None, True, DIFF, 0),
    ("разница, победа гостей", (0, 2), None, (1, 3), None, True, DIFF, 0),
    ("исход, победа хозяев", (3, 0), None, (2, 1), None, True, OUTCOME, 0),
    ("исход, победа гостей", (0, 1), None, (1, 3), None, True, OUTCOME, 0),
    ("промах, другой исход", (2, 0), None, (0, 1), None, True, 0, 0),
    ("промах, прогноз ничьей", (1, 1), None, (2, 1), None, True, 0, 0),
    ("промах, факт ничья", (2, 1), None, (1, 1), None, True, 0, 0),
    ("бомбардир + точный счёт", (2, 1), "701", (2, 1), "701", True, EXACT, FIRST_SCORER),
    ("бомбардир без счёта", (3, 0), "701", (1, 2), "701", True, 0, FIRST_SCORER),
    ("бомбардир + исход", (1, 0), "702", (3, 1), "702", True, OUTCOME, FIRST_SCORER),
    ("бомбардир не тот", (2, 1), "702", (2, 1), "701", True, EXACT, 0),
    ("бомбардир не указан", (2, 1), None, (2, 1), "701", True, EXACT, 0),
    ("Реал не забил (дома)", (1, 0), "701", (0, 1), None, True, 0, 0),
    ("Реал не забил, но в данных бомбардир", (1, 0), "701", (0, 2), "701", True, 0, 0),
    ("Реал в гостях: победа, бомбардир", (0, 2), "701", (1, 3), "701", False, DIFF, FIRST_SCORER),
    ("Реал в гостях: точный, бомбардир", (1, 3), "703", (1, 3), "703", False, EXACT, FIRST_SCORER),
    ("Реал в гостях не забил", (2, 0), "701", (2, 0), "701", False, EXACT, 0),
    ("Реал в гостях: забили только хозяева", (1, 1), "701", (3, 0), None, False, 0, 0),
    ("id игрока как число и строка", (1, 0), 701, (1, 0), "701", True, EXACT, FIRST_SCORER),
]


@pytest.mark.parametrize("name,pred,ps,act,as_,rm_home,score,bonus", CASES, ids=[c[0] for c in CASES])
def test_points_table(name, pred, ps, act, as_, rm_home, score, bonus):
    p = compute(pred[0], pred[1], ps, act[0], act[1], as_, rm_home)
    assert (p.score, p.scorer) == (score, bonus)
    assert p.total == score + bonus
    assert p.exact == (score == EXACT)


def test_constants():
    assert (EXACT, DIFF, OUTCOME, FIRST_SCORER) == (5, 3, 2, 2)
    assert (rules.GOALS_MIN, rules.GOALS_MAX) == (0, 20)


def test_kind():
    assert compute(1, 1, None, 2, 2, None, True).kind == "diff"
    assert compute(0, 0, None, 0, 0, None, True).kind == "exact"
    assert compute(0, 1, None, 0, 3, None, True).kind == "outcome"
    assert compute(0, 1, None, 1, 0, None, True).kind == "miss"
