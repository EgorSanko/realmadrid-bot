"""src/routes/games.py — Quiz + Mini games endpoints.

Эндпоинты (7):
- GET  /api/quiz/freeplay/question — без auth/cooldown/очков
- GET  /api/quiz/status            — всегда available (cooldown снят)
- GET  /api/quiz/question          — взять вопрос (без cooldown, без очков)
- POST /api/quiz/answer            — ответить (без cooldown, без очков)
- GET  /api/games/status           — cooldown для мини-игр (24ч)
- POST /api/games/start            — старт мини-игры
- POST /api/games/result           — результат (очки не дают, cooldown)

Shared state живёт в api.py: QUIZ_QUESTIONS, quiz_cooldowns,
quiz_asked_questions, quiz_question_started, _game_sessions, QUIZ_POINTS,
GAME_POINTS, _get_last_game_time, _set_cooldown.
"""
import random
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["games"])


class QuizAnswerRequest(BaseModel):
    difficulty: str
    question: str
    answer_index: int


class GameStartRequest(BaseModel):
    game: str
    difficulty: str


class GameResultRequest(BaseModel):
    game: str
    difficulty: str
    won: bool
    score: int


def init(get_current_user):
    @router.get("/quiz/freeplay/question")
    async def get_quiz_freeplay_question(difficulty: str):
        from api import QUIZ_QUESTIONS
        if difficulty not in QUIZ_QUESTIONS:
            raise HTTPException(status_code=400, detail="Неверная сложность")
        questions = QUIZ_QUESTIONS[difficulty]
        q = random.choice(questions)
        return {
            "question": q["q"], "answers": q["a"], "correct": q["correct"],
            "difficulty": difficulty, "timer_seconds": 15,
        }

    @router.get("/quiz/status")
    async def get_quiz_status(user: dict = Depends(get_current_user)):
        return {"available": True, "remaining_seconds": 0}

    @router.get("/quiz/question")
    async def get_quiz_question(difficulty: str, user: dict = Depends(get_current_user)):
        from api import QUIZ_QUESTIONS, quiz_asked_questions, quiz_question_started
        if difficulty not in QUIZ_QUESTIONS:
            raise HTTPException(status_code=400, detail="Неверная сложность")

        user_id = user['user_id']
        now = datetime.now().timestamp()

        if user_id not in quiz_asked_questions:
            quiz_asked_questions[user_id] = {}
        if difficulty not in quiz_asked_questions[user_id]:
            quiz_asked_questions[user_id][difficulty] = []

        asked = quiz_asked_questions[user_id][difficulty]
        all_q = QUIZ_QUESTIONS[difficulty]
        available = [q for q in all_q if q["q"] not in asked]
        if not available:
            quiz_asked_questions[user_id][difficulty] = []
            available = all_q

        random.shuffle(available)
        question = available[0]
        quiz_asked_questions[user_id][difficulty].append(question["q"])
        if len(quiz_asked_questions[user_id][difficulty]) > 50:
            quiz_asked_questions[user_id][difficulty] = quiz_asked_questions[user_id][difficulty][-50:]
        quiz_question_started[user_id] = now

        return {
            "question": question["q"], "answers": question["a"],
            "difficulty": difficulty, "points": 0,
            "timer_seconds": 15,
        }

    @router.post("/quiz/answer")
    async def submit_quiz_answer(req: QuizAnswerRequest, user: dict = Depends(get_current_user)):
        from api import QUIZ_QUESTIONS, quiz_question_started
        if req.difficulty not in QUIZ_QUESTIONS:
            raise HTTPException(status_code=400, detail="Неверная сложность")

        user_id = user['user_id']
        now = datetime.now().timestamp()

        question_start = quiz_question_started.get(user_id, 0)
        if question_start > 0 and (now - question_start) > 35:
            quiz_question_started.pop(user_id, None)
            return {"correct": False, "correct_index": -1, "points_earned": 0,
                    "next_quiz_in": 0, "timeout": True, "message": "Время вышло! (30 сек)"}

        question_data = None
        for q in QUIZ_QUESTIONS[req.difficulty]:
            if q["q"] == req.question:
                question_data = q
                break
        if not question_data:
            raise HTTPException(status_code=400, detail="Вопрос не найден")

        correct = req.answer_index == question_data["correct"]
        quiz_question_started.pop(user_id, None)

        return {"correct": correct, "correct_index": question_data["correct"],
                "points_earned": 0, "next_quiz_in": 0, "new_balance": None}

    @router.get("/games/status")
    async def get_games_status(user: dict = Depends(get_current_user)):
        from api import _get_last_game_time
        user_id = user['user_id']
        now = datetime.now().timestamp()
        last_played = _get_last_game_time(user_id)
        remaining = (last_played + 86400) - now
        if remaining > 0:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            return {"available": False, "remaining_seconds": remaining,
                    "remaining_text": f"{hours}ч {minutes}м"}
        return {"available": True}

    @router.post("/games/start")
    async def start_game(req: GameStartRequest, user: dict = Depends(get_current_user)):
        from api import _get_last_game_time, _set_cooldown, _game_sessions, GAME_POINTS
        user_id = user['user_id']
        now = datetime.now().timestamp()

        last_played = _get_last_game_time(user_id)
        if now - last_played < 86400:
            raise HTTPException(status_code=400, detail="Игра уже сыграна сегодня")
        if req.game not in ['penalty', 'catch', 'runner']:
            raise HTTPException(status_code=400, detail="Неизвестная игра")
        if req.difficulty not in GAME_POINTS:
            raise HTTPException(status_code=400, detail="Неверная сложность")

        _set_cooldown(user_id)
        _game_sessions[user_id] = {'started_at': now, 'result_submitted': False}
        return {"success": True, "game": req.game, "difficulty": req.difficulty,
                "message": "Игра началась! Попытка записана."}

    @router.post("/games/result")
    async def submit_game_result(req: GameResultRequest, user: dict = Depends(get_current_user)):
        from api import _set_cooldown, _game_sessions, GAME_POINTS
        user_id = user['user_id']
        if req.game not in ['penalty', 'catch', 'runner']:
            raise HTTPException(status_code=400, detail="Неизвестная игра")
        if req.difficulty not in GAME_POINTS:
            raise HTTPException(status_code=400, detail="Неверная сложность")

        session = _game_sessions.get(user_id)
        if session and session.get('result_submitted'):
            print(f"Double result blocked for user {user_id}", flush=True)
            return {"success": True, "won": req.won, "points_earned": 0, "next_game_in": 86400}

        if session:
            session['result_submitted'] = True
        _game_sessions[user_id] = {'started_at': datetime.now().timestamp(), 'result_submitted': True}
        _set_cooldown(user_id)
        return {"success": True, "won": req.won, "points_earned": 0, "next_game_in": 86400}
