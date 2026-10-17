"""Банк вопросов викторины: app/games/quiz_questions.json.

Формат: {"easy": [вопрос, …], "medium": …, "hard": …, "expert": …}, вопрос —
{id, q, a: [4 варианта], correct: индекс верного, media?: {type: player|team|league, id}, stale?, note?}.
`stale: true` — вопрос устарел или в нём ошибка: в игру не попадает (остаётся в файле для истории).
Перенесён из старого проекта (quiz_questions/*.json) и проверен на актуальность к октябрю 2026.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

PATH = Path(__file__).with_name("quiz_questions.json")
LEVELS = ("easy", "medium", "hard", "expert")
MEDIA_TYPES = ("player", "team", "league")


@dataclass(frozen=True)
class Question:
    id: str
    level: str
    q: str
    a: tuple[str, ...]
    correct: int
    media: Optional[dict[str, Any]] = None


def _check(level: str, raw: dict[str, Any]) -> Question:
    qid = raw["id"]
    a = raw["a"]
    if not isinstance(a, list) or len(a) != 4 or len(set(a)) != 4 or not all(isinstance(s, str) and s for s in a):
        raise ValueError(f"{qid}: нужно 4 разных варианта ответа")
    correct = raw["correct"]
    if not isinstance(correct, int) or not 0 <= correct < 4:
        raise ValueError(f"{qid}: correct вне 0..3")
    media = raw.get("media")
    if media is not None:
        if media.get("type") not in MEDIA_TYPES or not isinstance(media.get("id"), int):
            raise ValueError(f"{qid}: неверный media")
        media = {"type": media["type"], "id": media["id"]}
    return Question(qid, level, raw["q"].strip(), tuple(a), correct, media)


@lru_cache(maxsize=4)
def load(path: str = str(PATH)) -> dict[str, tuple[Question, ...]]:
    """Активные (не stale) вопросы по уровням. Ошибка формата — исключение при старте."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, tuple[Question, ...]] = {}
    ids: set[str] = set()
    for level in LEVELS:
        items = []
        for raw in data.get(level, []):
            if raw["id"] in ids:
                raise ValueError(f"повтор id вопроса: {raw['id']}")
            ids.add(raw["id"])
            q = _check(level, raw)
            if not raw.get("stale"):
                items.append(q)
        out[level] = tuple(items)
    return out
