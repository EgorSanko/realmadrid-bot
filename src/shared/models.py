"""src/shared/models.py — Pydantic request models.

Used by routes/bets.py, routes/prizes.py, routes/admin.py, routes/streams.py
through re-export from api.py.
"""
from typing import Optional, Union
from pydantic import BaseModel


class BetRequest(BaseModel):
    match_id: Optional[Union[str, int]] = None  # None для live-ставок (берётся из Leon)
    bet_type: str  # 'home', 'draw', 'away', 'score_X-X'
    amount: int


class PredictionRequest(BaseModel):
    match_id: Optional[Union[str, int]] = None
    prediction: str  # 'home', 'draw', 'away'


class SellBetRequest(BaseModel):
    bet_id: int


class ClaimPrizeRequest(BaseModel):
    prize_id: int
    contact: str
    size: Optional[str] = None  # Для футболки
    phone: Optional[str] = None  # Для TG Premium
    address: Optional[str] = None  # Для PlayStation


class AdminAddBalanceRequest(BaseModel):
    username: str
    amount: int


class _HeartbeatReq(BaseModel):
    client_id: str
