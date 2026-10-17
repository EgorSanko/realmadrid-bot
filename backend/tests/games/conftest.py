import random

import pytest
from fastapi.testclient import TestClient

from app.games import api as games_api
from app.games import bank
from app.main import app
from tests.predictions.conftest import (BOT_TOKEN, Clock, Mono, T0, clock, env, mono, provider,  # noqa: F401
                                        sign_init_data, svc, tma)


class ScriptedRng(random.Random):
    """random.Random, у которого прыжок вратаря и удар соперника можно задать заранее."""

    def __init__(self, seed: int = 7):
        super().__init__(seed)
        self.keepers: list[int] = []
        self.rival: list[bool] = []

    def randint(self, a, b):
        return self.keepers.pop(0) if self.keepers else super().randint(a, b)

    def random(self):
        if self.rival:
            return 0.0 if self.rival.pop(0) else 0.999999
        return super().random()


@pytest.fixture()
def rng():
    return ScriptedRng()


@pytest.fixture()
def games(svc, clock, mono, rng):  # noqa: F811
    g = games_api.configure(clock=clock, mono=mono, rng=rng)
    yield g
    games_api._service = None


@pytest.fixture()
def client(games):
    return TestClient(app)


def correct_choice(question: dict) -> int:
    """Индекс верного варианта в показанном (перемешанном) порядке — по банку, как знал бы знаток."""
    for qs in bank.load().values():
        for q in qs:
            if q.q == question["q"] and sorted(q.a) == sorted(question["a"]):
                return question["a"].index(q.a[q.correct])
    raise AssertionError("вопрос не найден в банке")
