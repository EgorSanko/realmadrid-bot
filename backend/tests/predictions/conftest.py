import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.predictions import api
from app.predictions.provider import FakeProvider

BOT_TOKEN = "123456:TEST-fake-bot-token"
RM = {"id": 8633, "name": "Реал Мадрид"}
OPP = {"id": 8302, "name": "Севилья"}
SQUAD = [{"id": 701, "name": "Мбаппе"}, {"id": 702, "name": "Винисиус"},
         {"id": 703, "name": "Беллингем"}, {"id": 704, "name": "Гюлер"}]
T0 = datetime(2026, 10, 18, 19, 0, tzinfo=timezone.utc)  # Вс, 18 окт, 22:00 МСК


def sign_init_data(user_id: int, bot_token: str = BOT_TOKEN, auth_date: int | None = None,
                   first_name: str = "Тест", **extra) -> str:
    """initData, подписанный по алгоритму Telegram (WebAppData → HMAC-SHA256)."""
    user = {"id": user_id, "first_name": first_name, **extra}
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAEtest",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def tma(user_id: int, **kw) -> dict:
    return {"Authorization": "tma " + sign_init_data(user_id, **kw)}


def mk_match(mid, kickoff=T0, rm_home=True, status="scheduled", score=None, scorer=None, opp=OPP):
    return {"id": str(mid), "kickoff_utc": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "home": RM if rm_home else opp, "away": opp if rm_home else RM,
            "status": status, "score": None if score is None else {"home": score[0], "away": score[1]},
            "first_rm_scorer_player_id": scorer, "rm_squad": SQUAD}


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def set(self, t: datetime) -> None:
        self.t = t


class Mono:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BOT_TOKEN", BOT_TOKEN)
    monkeypatch.delenv("RM_TEAM_ID", raising=False)
    return tmp_path


@pytest.fixture()
def clock():
    return Clock(T0 - timedelta(days=1))


@pytest.fixture()
def mono():
    return Mono()


@pytest.fixture()
def provider():
    return FakeProvider()


@pytest.fixture()
def svc(env, provider, clock, mono):
    s = api.configure(provider=provider, db_path=str(env / "predictions.db"), clock=clock,
                      bot_username="madridista_bot", rate_clock=mono)
    yield s
    api._service = None


@pytest.fixture()
def client(svc):
    return TestClient(app)


def predict(client, uid, mid, home, away, scorer=None, **kw):
    body = {"home": home, "away": away}
    if scorer is not None:
        body["first_scorer_id"] = scorer
    return client.put(f"/api/predict/matches/{mid}", json=body, headers=tma(uid, **kw))
