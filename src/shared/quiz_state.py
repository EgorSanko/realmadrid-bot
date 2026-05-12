"""src/shared/quiz_state.py — In-memory quiz + games state.

Loaded at module import:
- QUIZ_QUESTIONS: dict[difficulty → list[question]]
- QUIZ_POINTS, GAME_POINTS: rewards by difficulty

Runtime state (per user_id):
- quiz_cooldowns, quiz_question_started, quiz_asked_questions
- _game_sessions: track active game sessions

Imported by routes/games.py.
"""
from datetime import datetime


# ============ ВИКТОРИНА ============

import random

# Вопросы викторины по сложности
# ============ ВИКТОРИНА ============

import json
import os

# Загрузка вопросов из JSON файлов
def load_quiz_questions():
    questions = {}
    quiz_dir = os.path.join(os.path.dirname(__file__), "..", "..", "quiz_questions")

    for difficulty in ['easy', 'medium', 'hard', 'expert']:
        filepath = os.path.join(quiz_dir, f'{difficulty}.json')
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                questions[difficulty] = json.load(f)
                print(f"Loaded {len(questions[difficulty])} {difficulty} questions")
        except Exception as e:
            print(f"Error loading {difficulty} questions: {e}")
            questions[difficulty] = []

    return questions

QUIZ_QUESTIONS = load_quiz_questions()

QUIZ_POINTS = {'easy': 5, 'medium': 10, 'hard': 15, 'expert': 25}

# Cooldown хранилище (в памяти + БД для надёжности)
quiz_cooldowns = {}
quiz_question_started = {}
quiz_asked_questions = {}
_game_sessions = {}  # user_id -> {'started_at': datetime, 'result_submitted': bool}

def _get_last_game_time(user_id: int) -> float:
    """Получить время последней игры из БД"""
    # Сначала проверяем память
    if user_id in quiz_cooldowns:
        mem_time = quiz_cooldowns[user_id]
        if isinstance(mem_time, (int, float)):
            return mem_time
        elif isinstance(mem_time, datetime):
            return mem_time.timestamp()

    # Потом БД
    try:
        from database import _execute
        row = _execute(
            "SELECT created_at FROM transactions WHERE user_id = ? AND type IN ('game_win', 'quiz_win', 'bonus') AND description LIKE '%Игра%' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        if row:
            from datetime import datetime as dt
            ts = row[0].get('created_at', '')
            if ts:
                try:
                    t = dt.strptime(ts, '%Y-%m-%d %H:%M:%S')
                    return t.timestamp()
                except:
                    pass
    except:
        pass
    return 0

def _set_cooldown(user_id: int):
    """Установить cooldown в памяти"""
    quiz_cooldowns[user_id] = datetime.now().timestamp()


GAME_POINTS = {'easy': 5, 'medium': 10, 'hard': 15, 'expert': 25}
