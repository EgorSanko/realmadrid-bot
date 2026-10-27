"""HTTP-слой прогнозов: /api/predict/*. Ошибки — JSON {error, message} по-русски (?lang=en — по-английски,
app/i18n.py; коды те же). ?lang=en — «Болельщик» (пользователь без имени) в рейтингах и лигах → «Fan».

Подключение в main.py: `predictions.api.install(app)`.
Источник матчей: `configure(provider=...)`; по умолчанию — SnapshotProvider (пока заглушка).
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app import i18n
from app.auth import InitDataError
from app.identity import authenticate, has_credentials

from .service import PredictError, PredictionService
from .snapshot_provider import SnapshotProvider

PREFIX = "/api/predict"
router = APIRouter(prefix=PREFIX)

_service: Optional[PredictionService] = None


def configure(**kw: Any) -> PredictionService:
    """Создаёт сервис заново: provider, db_path, clock, bot_username, rate_clock."""
    global _service
    kw.setdefault("provider", SnapshotProvider())
    _service = PredictionService(**kw)
    return _service


def get_service() -> PredictionService:
    return _service or configure()


def _ok(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _okl(request: Request, body: Any, status: int = 200) -> JSONResponse:
    """Ответ с именами пользователей: ?lang=en — «Болельщик» → «Fan»."""
    return _ok(i18n.fan_names(body, i18n.request_lang(request)), status)


def _err(status: int, error: str, message: str) -> JSONResponse:
    return _ok({"error": error, "message": message}, status)


# ---------- авторизация ----------

def _auth(request: Request, authorization: Optional[str], svc: PredictionService) -> int:
    """initData мини-аппа или наша сессия (заголовок `Session …` / cookie rm_session) — app/identity.py."""
    try:
        p = authenticate(request, authorization, svc)
    except InitDataError as e:
        raise PredictError(401, "unauthorized", e.message) from None
    if p.tg_user is not None:
        return svc.upsert_user(p.tg_user)
    return p.id


def current_user(request: Request, authorization: Optional[str] = Header(default=None),
                 svc: PredictionService = Depends(get_service)) -> int:
    return _auth(request, authorization, svc)


def optional_user(request: Request, authorization: Optional[str] = Header(default=None),
                  svc: PredictionService = Depends(get_service)) -> Optional[int]:
    """Без входа или с невалидным — аноним (только чтение, без своего места)."""
    if not has_credentials(request, authorization):
        return None
    try:
        return _auth(request, authorization, svc)
    except PredictError:
        return None


# ---------- тела запросов ----------

class PredictionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home: StrictInt = Field(ge=0, le=20)
    away: StrictInt = Field(ge=0, le=20)
    first_scorer_id: Optional[Union[StrictInt, StrictStr]] = None


class LeagueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr


class JoinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: StrictStr


# ---------- эндпоинты ----------

@router.get("/matches")
def get_matches(request: Request, user: Optional[int] = Depends(optional_user),
                svc: PredictionService = Depends(get_service)):
    return _okl(request, svc.matches(user))


@router.put("/matches/{match_id}")
def put_match(match_id: str, body: PredictionIn, user: int = Depends(current_user),
              svc: PredictionService = Depends(get_service)):
    return _ok(svc.put_prediction(user, match_id, body.home, body.away, body.first_scorer_id))


@router.get("/leaderboard")
def get_leaderboard(request: Request, period: Literal["season", "month"] = "season", league: Optional[int] = None,
                    limit: int = Query(50, ge=1, le=1000), user: Optional[int] = Depends(optional_user),
                    svc: PredictionService = Depends(get_service)):
    return _okl(request, svc.leaderboard(period, league, limit, user))


@router.get("/me")
def get_me(request: Request, user: int = Depends(current_user), svc: PredictionService = Depends(get_service)):
    return _okl(request, svc.me(user))


@router.get("/leagues")
def get_leagues(request: Request, user: int = Depends(current_user), svc: PredictionService = Depends(get_service)):
    return _okl(request, svc.my_leagues(user))


@router.post("/leagues")
def post_league(body: LeagueIn, user: int = Depends(current_user), svc: PredictionService = Depends(get_service)):
    return _ok(svc.create_league(user, body.name), 201)


@router.get("/leagues/{league_id}")
def get_league(request: Request, league_id: int, user: int = Depends(current_user),
               svc: PredictionService = Depends(get_service)):
    return _okl(request, svc.league(user, league_id))


@router.post("/leagues/join")
def post_join(body: JoinIn, user: int = Depends(current_user), svc: PredictionService = Depends(get_service)):
    return _ok(svc.join_league(user, body.code))


@router.delete("/leagues/{league_id}/membership")
def delete_membership(league_id: int, user: int = Depends(current_user),
                      svc: PredictionService = Depends(get_service)):
    return _ok(svc.leave_league(user, league_id))


@router.patch("/leagues/{league_id}")
def patch_league(league_id: int, body: LeagueIn, user: int = Depends(current_user),
                 svc: PredictionService = Depends(get_service)):
    return _ok(svc.rename_league(user, league_id, body.name))


@router.delete("/leagues/{league_id}")
def delete_league(league_id: int, user: int = Depends(current_user), svc: PredictionService = Depends(get_service)):
    return _ok(svc.delete_league(user, league_id))


# ---------- ошибки ----------

_FIELD_MSG = {
    "home": "Голы — целые числа от 0 до 20",
    "away": "Голы — целые числа от 0 до 20",
    "first_scorer_id": "Неверный id игрока",
    "name": "Название лиги — строка до 40 символов",
    "code": "Введите код приглашения",
    "period": "period: season или month",
    "limit": "limit: от 1 до 1000",
    "league": "league: id лиги — число",
    "league_id": "Неверный id лиги",
}


def _validation_message(exc: RequestValidationError) -> str:
    for e in exc.errors():
        for part in reversed(e.get("loc", ())):
            if part in _FIELD_MSG:
                return _FIELD_MSG[part]
        if e.get("type") == "extra_forbidden":
            return f"Лишнее поле: {e['loc'][-1]}"
    return "Неверный запрос"


async def _on_predict_error(request: Request, exc: PredictError):
    return _err(exc.status, exc.error, exc.message)


async def _on_validation(request: Request, exc: RequestValidationError):
    if request.url.path.startswith((PREFIX, "/api/games")):
        return _err(422, "validation", _validation_message(exc))
    return await request_validation_exception_handler(request, exc)


def install(app: FastAPI) -> None:
    app.include_router(router)
    app.add_exception_handler(PredictError, _on_predict_error)
    app.add_exception_handler(RequestValidationError, _on_validation)
