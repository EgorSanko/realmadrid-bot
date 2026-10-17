"""HTTP-слой мини-игр: /api/games/*. Ошибки — JSON {error, message} по-русски.

Вход — тот же, что у прогнозов (initData мини-аппа, заголовок Session, cookie rm_session; app/identity.py).
Играть можно без входа: тогда итог не сохраняется на сервере (клиент держит рекорд на устройстве).

  GET  /api/games/info                         уровни и правила
  POST /api/games/quiz/start      {level}      новая партия викторины
  POST /api/games/quiz/{sid}/next              выдать вопрос (тут стартует серверный таймер)
  POST /api/games/quiz/{sid}/answer {choice}   ответ: 0..3 или null (время вышло)
  POST /api/games/penalty/start   {level}      новая серия пенальти
  POST /api/games/penalty/{sid}/shot {zone}    удар в зону 1..6 → outcome: goal / save / post / bar
  GET  /api/games/me                           мои рекорды (нужен вход)
  GET  /api/games/leaderboard?game=quiz|penalty  лучшие за неделю
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from ..predictions import api as predict_api
from .service import GameError, GameService

PREFIX = "/api/games"
router = APIRouter(prefix=PREFIX)

_service: Optional[GameService] = None


def configure(**kw: Any) -> GameService:
    """Создаёт сервис заново (тесты: clock, mono, rng, questions). База — та же predictions.db."""
    global _service
    kw.setdefault("conn", lambda: predict_api.get_service().conn())
    _service = GameService(**kw)
    return _service


def get_service() -> GameService:
    return _service or configure()


def _ok(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _rate_key(request: Request, user: Optional[int]) -> Any:
    return ("u", user) if user is not None else ("ip", request.client.host if request.client else "?")


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        data = None
    if not isinstance(data, dict):
        raise GameError(400, "bad_request", "Тело запроса — JSON-объект")
    return data


@router.get("/info")
def get_info(svc: GameService = Depends(get_service)):
    return _ok(svc.info())


@router.post("/quiz/start")
async def quiz_start(request: Request, user: Optional[int] = Depends(predict_api.optional_user),
                     svc: GameService = Depends(get_service)):
    body = await _body(request)
    return _ok(svc.quiz_start(body.get("level"), user, _rate_key(request, user)))


@router.post("/quiz/{sid}/next")
def quiz_next(sid: str, request: Request, user: Optional[int] = Depends(predict_api.optional_user),
              svc: GameService = Depends(get_service)):
    return _ok(svc.quiz_next(sid, user, _rate_key(request, user)))


@router.post("/quiz/{sid}/answer")
async def quiz_answer(sid: str, request: Request, user: Optional[int] = Depends(predict_api.optional_user),
                      svc: GameService = Depends(get_service)):
    body = await _body(request)
    if "choice" not in body:
        raise GameError(400, "bad_choice", "Нужен вариант ответа (choice) или null")
    return _ok(svc.quiz_answer(sid, body["choice"], user, _rate_key(request, user)))


@router.post("/penalty/start")
async def penalty_start(request: Request, user: Optional[int] = Depends(predict_api.optional_user),
                        svc: GameService = Depends(get_service)):
    body = await _body(request)
    return _ok(svc.penalty_start(body.get("level"), user, _rate_key(request, user)))


@router.post("/penalty/{sid}/shot")
async def penalty_shot(sid: str, request: Request, user: Optional[int] = Depends(predict_api.optional_user),
                       svc: GameService = Depends(get_service)):
    body = await _body(request)
    return _ok(svc.penalty_shot(sid, body.get("zone"), user, _rate_key(request, user)))


@router.get("/me")
def get_me(user: int = Depends(predict_api.current_user), svc: GameService = Depends(get_service)):
    return _ok(svc.me(user))


@router.get("/leaderboard")
def get_leaderboard(game: str = "quiz", limit: int = Query(20, ge=1, le=100),
                    user: Optional[int] = Depends(predict_api.optional_user),
                    svc: GameService = Depends(get_service)):
    return _ok(svc.leaderboard(game, limit, user))


async def _on_game_error(request: Request, exc: GameError):
    return _ok({"error": exc.error, "message": exc.message}, exc.status)


def install(app: FastAPI) -> None:
    app.include_router(router)
    app.add_exception_handler(GameError, _on_game_error)
