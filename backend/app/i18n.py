"""Язык ответа API: `?lang=en` — английский, всё остальное (нет параметра, `ru`, мусор) — русский, как раньше.

Фронтенд при английском интерфейсе дописывает `lang=en` к каждому запросу /api/…, поэтому ответы на разных
языках — разные URL: браузерный кэш (Cache-Control: public) их не смешивает, nginx /api/ не кэширует
(proxy_cache off) и строку запроса передаёт как есть.

Здесь:
  * `lang()` / `request_lang()` — разбор параметра (только 'en' меняет поведение);
  * `msg()` — английский текст сообщений об ошибках (`message` / `detail`); коды ошибок не меняются;
  * `EnglishErrors` — ASGI-прослойка: при `lang=en` подменяет русские `message`/`detail` в JSON-ответах
    с кодом ≥ 400 — одно место на все модули (прогнозы, игры, вход, счётчик, сам main);
  * мелкие подписи: названия источников новостей, «Болельщик», месяцы недели рейтинга.
Перевод новостей, видео и фактов матча — app/translate.py, вопросы викторины — app/games/quiz_questions_en.json.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import parse_qs

EN = "en"
RU = "ru"


def lang(value: Any) -> str:
    """'en' (без учёта регистра и пробелов) → 'en', иначе 'ru'."""
    return EN if isinstance(value, str) and value.strip().lower() == EN else RU


def query_lang(query_string: bytes | str) -> str:
    qs = query_string.decode("latin-1") if isinstance(query_string, bytes) else query_string
    vals = parse_qs(qs, keep_blank_values=True).get("lang") or []
    return lang(vals[0]) if vals else RU


def request_lang(request: Any) -> str:
    try:
        return lang(request.query_params.get("lang"))
    except Exception:
        return RU


# ---------- сообщения об ошибках ----------

MESSAGES_EN: dict[str, str] = {
    # общие
    "Неверный запрос": "Invalid request",
    "Слишком большой запрос": "Request is too large",
    "Запрос с чужого сайта отклонён": "Cross-site request rejected",
    "Нужна авторизация": "Sign-in required",
    "Нет доступа": "Access denied",
    "Тело запроса — JSON-объект": "Request body must be a JSON object",
    "Слишком много запросов — подождите": "Too many requests — please wait",
    "Слишком частые запросы — подождите минуту": "Too many requests — please wait a minute",
    "Слишком много попыток — подождите минуту": "Too many attempts — please wait a minute",
    "Слишком много попыток — подождите несколько минут": "Too many attempts — please wait a few minutes",
    "device: случайный id устройства": "device: a random device id",
    "platform: tg, android или web": "platform: tg, android or web",
    # вход (app/auth.py, app/identity.py, app/auth_api.py)
    "Вход через Telegram не настроен": "Telegram sign-in is not configured",
    "Подпись Telegram не прошла проверку": "Telegram signature check failed",
    "В данных Telegram нет пользователя": "No user in the Telegram data",
    "Неверные данные входа": "Invalid sign-in data",
    "Данные входа устарели — войдите ещё раз": "Sign-in data has expired — please sign in again",
    "Сессия недействительна — войдите снова": "Session is invalid — please sign in again",
    "Сессия истекла — войдите снова": "Session has expired — please sign in again",
    "Слишком много попыток входа — подождите минуту": "Too many sign-in attempts — please wait a minute",
    "Слишком много кодов входа — подождите несколько минут": "Too many sign-in codes — please wait a few minutes",
    "Сейчас слишком много входов — попробуйте через минуту": "Too many sign-ins right now — try again in a minute",
    "Вход по коду проверки выключен": "Review-code sign-in is disabled",
    "Вход по коду проверки настроен неверно": "Review-code sign-in is misconfigured",
    "Неверный код": "Invalid code",
    "Подтвердите удаление аккаунта": "Please confirm account deletion",
    # мини-игры (app/games)
    "Нужен вариант ответа (choice) или null": "An answer option (choice) or null is required",
    "Игра не найдена или устарела — начните заново": "Game not found or expired — start a new one",
    "Слишком часто — подождите немного": "Too often — please wait a moment",
    "Неизвестный уровень": "Unknown level",
    "Вопросы для этого уровня пока не готовы": "Questions for this level are not ready yet",
    "Игра уже закончилась": "The game is already over",
    "Вариант ответа — число от 0 до 3": "The answer option must be a number from 0 to 3",
    "Сначала нужно получить вопрос": "Get the question first",
    "Слишком быстро — прочитайте вопрос": "Too fast — read the question first",
    "Серия уже закончилась": "The shootout is already over",
    "Слишком быстро — дождитесь удара": "Too fast — wait for the kick",
    "Игра: quiz или penalty": "Game: quiz or penalty",
    # прогнозы (app/predictions)
    "Голы — целые числа от 0 до 20": "Goals must be whole numbers from 0 to 20",
    "Неверный id игрока": "Invalid player id",
    "Название лиги — строка до 40 символов": "League name must be a string of up to 40 characters",
    "Введите код приглашения": "Enter an invite code",
    "period: season или month": "period: season or month",
    "limit: от 1 до 1000": "limit: from 1 to 1000",
    "league: id лиги — число": "league: the league id must be a number",
    "Неверный id лиги": "Invalid league id",
    "Данные о матчах пока не подключены": "Match data is not connected yet",
    "Слишком часто: не больше 30 изменений прогноза в минуту":
        "Too often: no more than 30 prediction changes per minute",
    "Матч не найден": "Match not found",
    "Матч отменён — прогнозы не принимаются": "The match has been cancelled — predictions are closed",
    "Приём закрыт: матч уже начался": "Predictions are closed: the match has already started",
    "По вашему прогнозу Реал не забивает — автора первого гола выбрать нельзя":
        "In your prediction Real Madrid don't score — you can't pick the first goalscorer",
    "Этого игрока нет в составе Реала на матч": "This player is not in Real Madrid's squad for the match",
    "Рейтинг лиги виден только её участникам — войдите через Telegram":
        "The league table is visible to its members only — sign in with Telegram",
    "Лига не найдена": "League not found",
    "Вы не состоите в этой лиге": "You are not a member of this league",
    "Введите название лиги": "Enter a league name",
    "В названии недопустимые символы": "The name contains invalid characters",
    "Не удалось создать код приглашения": "Could not create an invite code",
    "Неверный код приглашения": "Invalid invite code",
    "Создатель не может выйти из лиги — её можно удалить": "The creator can't leave the league — it can be deleted",
    "Переименовать лигу может только её создатель": "Only the league's creator can rename it",
    "Удалить лигу может только её создатель": "Only the league's creator can delete it",
    # данные (app/main.py, поле detail)
    "матча нет ни в снимках, ни в календаре": "the match is neither in snapshots nor in the fixture list",
    "неверный id игрока": "invalid player id",
    "такого игрока нет у источника": "the source has no such player",
    "источники не ответили, попробуем позже": "sources did not respond, we'll try again later",
    "очередь сборщика переполнена": "the collector queue is full",
    "неверный id новости": "invalid news id",
    "такой новости нет": "no such news item",
}

# сообщения с числами и именами полей
_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^Лишнее поле: (.+)$"), "Unexpected field: {0}"),
    (re.compile(r"^Зона удара — число от 1 до (\d+)$"), "The shot zone must be a number from 1 to {0}"),
    (re.compile(r"^Название лиги — не длиннее (\d+) символов$"), "League name must be at most {0} characters"),
    (re.compile(r"^Можно создать не больше (\d+) лиг$"), "You can create at most {0} leagues"),
    (re.compile(r"^Можно состоять не больше чем в (\d+) лигах$"), "You can be a member of at most {0} leagues"),
    (re.compile(r"^(.+): сборщик ещё не получил данные$"), "{0}: the collector has not received data yet"),
)


def msg(text: Any, lng: str = EN) -> Any:
    """Английский вариант сообщения; неизвестное — как есть (лучше русский текст, чем пустой)."""
    if lng != EN or not isinstance(text, str):
        return text
    if text in MESSAGES_EN:
        return MESSAGES_EN[text]
    for rx, tpl in _PATTERNS:
        m = rx.match(text)
        if m:
            return tpl.format(*m.groups())
    return text


def localize_error_body(body: bytes) -> bytes:
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if not isinstance(data, dict):
        return body
    changed = False
    for k in ("message", "detail"):
        v = data.get(k)
        if isinstance(v, str):
            nv = msg(v, EN)
            if nv != v:
                data[k] = nv
                changed = True
    if not changed:
        return body
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class EnglishErrors:
    """ASGI-прослойка: `lang=en` + ответ /api/… с кодом ≥ 400 и JSON → `message`/`detail` по-английски.
    Остальные ответы (в т.ч. потоковые) проходят без буферизации."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/api/")
                or query_lang(scope.get("query_string", b"")) != EN):
            await self.app(scope, receive, send)
            return
        held: dict[str, Any] = {}
        parts: list[bytes] = []

        async def wrapped(message):
            if message["type"] == "http.response.start":
                ctype = next((v for k, v in message.get("headers", []) if k.lower() == b"content-type"), b"")
                if message["status"] >= 400 and ctype.startswith(b"application/json"):
                    held["start"] = message
                    return
                await send(message)
                return
            if message["type"] == "http.response.body" and "start" in held:
                parts.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = localize_error_body(b"".join(parts))
                start = held.pop("start")
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, wrapped)


# ---------- подписи ----------

# названия лент новостей (media.NEWS_FEEDS, поле source и also)
SOURCES_EN = {"Чемпионат": "Championat", "Спорт-Экспресс": "Sport-Express"}


def source_name(name: Optional[str], lng: str) -> Optional[str]:
    return SOURCES_EN.get(name, name) if lng == EN and name else name


FAN_RU, FAN_EN = "Болельщик", "Fan"  # имя пользователя без имени и ника (predictions.service.display_name)


def fan_names(obj: Any, lng: str) -> Any:
    """Рейтинги и лиги: «Болельщик» в полях name → «Fan». Обходит ответ целиком (он небольшой)."""
    if lng != EN:
        return obj
    if isinstance(obj, dict):
        return {k: (FAN_EN if k == "name" and v == FAN_RU else fan_names(v, lng)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fan_names(v, lng) for v in obj]
    return obj


MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December")
