"""Адаптер «снимки сборщика → MatchProvider». ЗАГЛУШКА.

Сборщик данных (этап 1, app/collector*, app/store.py) пишет снимки `fixtures` и `match:<id>`
в DATA_DIR/rm.sqlite3, но их окончательная форма ещё не зафиксирована. Когда зафиксируется,
здесь нужно реализовать три метода по контракту из `provider.py`:

  get_match(id)   — из снимка `match:<id>` (или строки `fixtures`, если снимка матча нет):
                    kickoff_utc, home/away {id,name}, status (привести к
                    scheduled|live|finished|cancelled|postponed), score {home,away} БЕЗ серии
                    пенальти, first_rm_scorer_player_id (первый гол Реала из событий; автогол
                    соперника — решение владельца), rm_squad (заявка/состав Реала: [{id,name}]).
  upcoming(limit) — незавершённые матчи из `fixtures` по возрастанию kickoff.
  recent(limit)   — завершённые матчи из `fixtures`, от новых к старым.

Подключение: `app.predictions.api.configure(provider=SnapshotProvider())` — по умолчанию
API использует именно этот класс, так что до реализации эндпоинты, которым нужны матчи,
отвечают 503 «Данные о матчах пока не подключены».
"""
from __future__ import annotations

from typing import Optional

from .provider import Match

_MSG = ("SnapshotProvider ещё не реализован: форма снимков сборщика не зафиксирована. "
        "См. docstring app/predictions/snapshot_provider.py")


class SnapshotProvider:
    def get_match(self, match_id: str) -> Optional[Match]:
        raise NotImplementedError(_MSG)

    def upcoming(self, limit: int) -> list[Match]:
        raise NotImplementedError(_MSG)

    def recent(self, limit: int) -> list[Match]:
        raise NotImplementedError(_MSG)
