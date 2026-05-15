"""src/shared/sheets_stub.py — drop-in replacement for google_sheets.GoogleSheetsClient.

Реальный Sheets-источник был отключён 2026-05-15: таблицы не наполнялись,
авторасчёт и уведомления зависли. Все нужные данные теперь идут из FotMob
через src/parsers/fotmob.py. Этот стаб сохраняет старую сигнатуру методов
чтобы не переписывать все call-sites одним махом.

get_matches() проксируется на FotMob fallback из api.py monkey-patch
(см. api.py: `sheets_client.get_matches = _sheets_get_matches_with_fallback`).
Остальные методы возвращают пустые структуры — call-sites уже умеют это
обрабатывать (там везде `if sheets_client and ...`).
"""

from typing import List, Dict, Optional


class SheetsStub:
    """No-op заглушка с тем же API что и GoogleSheetsClient.

    Реальная отдача данных идёт через monkey-patch в api.py:
        sheets_client.get_matches = _sheets_get_matches_with_fallback
    """

    def __init__(self, *args, **kwargs):
        pass

    def get_matches(self, limit: int = 5) -> List[Dict]:
        return []

    def get_all_upcoming_matches(self) -> List[Dict]:
        return []

    def get_results(self, limit: int = 5) -> List[Dict]:
        return []

    def get_standings(self, limit: int = 20) -> List[Dict]:
        return []

    def get_player_stats(self, limit: int = 10) -> List[Dict]:
        return []

    def get_odds(self) -> Optional[Dict]:
        return {}

    def get_form(self) -> str:
        return ''
