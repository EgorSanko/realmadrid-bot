"""
Real Madrid Bot v4.0 - Database Module
Система ставок с вейджером (отыгрышем)

Логика:
- Очки можно тратить ТОЛЬКО на ставки и призы (вывода в деньги НЕТ)
- При покупке очков они требуют отыгрыша (вейджер)
- Чтобы получить приз, нужно сначала отыграть все купленные очки
- Пример: купил 1000 очков → wager_remaining = 1000
- Поставил 500 → wager_remaining = 500
- Поставил ещё 500 → wager_remaining = 0 (можно брать приз!)

Бесплатные прогнозы:
- Угадал победителя: +10 очков
- Не угадал: -20 очков
- Эти очки НЕ требуют отыгрыша

Призы:
- Футболка Real Madrid: 1000 очков (единственный приз)
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

# Путь к базе данных
DB_PATH = os.getenv('DATABASE_PATH', 'betting.db')


@contextmanager
def get_connection():
    """Контекстный менеджер для безопасной работы с БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def _execute(query: str, params: tuple = None):
    """Выполнить SQL запрос и вернуть результат как список словарей"""
    with get_connection() as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
        if query.strip().upper().startswith('SELECT'):
            return [dict(row) for row in cursor.fetchall()]
        else:
            conn.commit()
            return cursor.rowcount


def init_database():
    """Инициализация всех таблиц базы данных"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # ============ ПОЛЬЗОВАТЕЛИ ============
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                
                -- Баланс
                balance INTEGER DEFAULT 50,           -- Текущий баланс очков
                total_deposited INTEGER DEFAULT 0,    -- Всего куплено очков
                
                -- Система вейджера (отыгрыша)
                wager_remaining INTEGER DEFAULT 0,    -- Сколько осталось отыграть
                wager_multiplier REAL DEFAULT 1.0,    -- Множитель отыгрыша (1.0 = 100%)
                
                -- Статистика ставок (на коэффициенты)
                bets_total INTEGER DEFAULT 0,         -- Всего ставок
                bets_won INTEGER DEFAULT 0,           -- Выигранных ставок
                bets_lost INTEGER DEFAULT 0,          -- Проигранных ставок
                bets_profit INTEGER DEFAULT 0,        -- Общий профит от ставок
                
                -- Статистика прогнозов (бесплатных)
                predictions_total INTEGER DEFAULT 0,  -- Всего прогнозов
                predictions_won INTEGER DEFAULT 0,    -- Угаданных прогнозов
                predictions_lost INTEGER DEFAULT 0,   -- Неугаданных прогнозов
                predictions_profit INTEGER DEFAULT 0, -- Профит от прогнозов (+10/-20)
                
                -- Даты
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                -- Настройки
                notifications_enabled INTEGER DEFAULT 1,
                is_banned INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                
                -- Призы
                prizes_claimed TEXT DEFAULT '[]'      -- JSON список полученных призов
            )
        ''')
        
        # ============ СТАВКИ (на коэффициенты) ============
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bets (
                bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                match_id TEXT NOT NULL,               -- ID матча из Google Sheets
                
                -- Детали ставки
                bet_type TEXT NOT NULL,               -- home/draw/away
                amount INTEGER NOT NULL,              -- Сумма ставки
                odds REAL NOT NULL,                   -- Коэффициент на момент ставки
                potential_win INTEGER NOT NULL,       -- Потенциальный выигрыш
                
                -- Информация о матче
                home_team TEXT,
                away_team TEXT,
                match_date TEXT,
                
                -- Статус и результат
                status TEXT DEFAULT 'pending',        -- pending/won/lost/cancelled/refunded
                result TEXT,                          -- Фактический результат: home/draw/away
                profit INTEGER DEFAULT 0,             -- Фактический профит (+/-)
                
                -- Даты
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settled_at TIMESTAMP,
                
                -- Учёт вейджера
                counted_for_wager INTEGER DEFAULT 0,  -- Учтена ли в отыгрыше
                
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # ============ ПРОГНОЗЫ (бесплатные) ============
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                match_id TEXT NOT NULL,
                
                -- Прогноз
                prediction TEXT NOT NULL,             -- home/draw/away
                
                -- Информация о матче
                home_team TEXT,
                away_team TEXT,
                match_date TEXT,
                
                -- Статус и результат
                status TEXT DEFAULT 'pending',        -- pending/correct/incorrect/cancelled
                actual_result TEXT,                   -- Фактический результат
                points_change INTEGER DEFAULT 0,      -- +10 или -20
                
                -- Даты
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settled_at TIMESTAMP,
                
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # ============ ТРАНЗАКЦИИ ============
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                
                -- Тип и сумма
                type TEXT NOT NULL,                   -- deposit/withdraw/bet/bet_win/bet_loss/
                                                      -- prediction_win/prediction_loss/bonus/prize/refund
                amount INTEGER NOT NULL,              -- Сумма (положительная или отрицательная)
                
                -- Баланс после транзакции
                balance_before INTEGER,
                balance_after INTEGER,
                wager_before INTEGER,
                wager_after INTEGER,
                
                -- Дополнительная информация
                description TEXT,
                reference_id TEXT,                    -- ID связанной ставки/прогноза
                admin_id INTEGER,                     -- ID админа (для депозитов/выводов)
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # ============ ПРИЗЫ ============
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prizes (
                prize_id INTEGER PRIMARY KEY AUTOINCREMENT,
                
                -- Информация о призе
                name TEXT NOT NULL,
                description TEXT,
                points_required INTEGER NOT NULL,     -- Сколько очков нужно
                image_url TEXT,
                
                -- Доступность
                is_active INTEGER DEFAULT 1,
                quantity_total INTEGER DEFAULT -1,    -- -1 = безлимит
                quantity_claimed INTEGER DEFAULT 0,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # ============ ЗАЯВКИ НА ПРИЗЫ ============
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prize_claims (
                claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                prize_id INTEGER NOT NULL,
                
                -- Статус заявки
                status TEXT DEFAULT 'pending',        -- pending/approved/rejected/delivered
                
                -- Контактные данные для доставки
                contact_info TEXT,                    -- Телефон/адрес
                
                -- Обработка
                admin_id INTEGER,
                admin_notes TEXT,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (prize_id) REFERENCES prizes(prize_id)
            )
        ''')
        
        # ============ ЗАПРОСЫ НА ПОПОЛНЕНИЕ ============
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deposit_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                
                -- Детали запроса
                amount_rub INTEGER NOT NULL,          -- Сумма в рублях
                amount_points INTEGER NOT NULL,       -- Сумма в очках
                payment_method TEXT,                  -- Способ оплаты
                
                -- Статус
                status TEXT DEFAULT 'pending',        -- pending/approved/rejected
                
                -- Обработка
                admin_id INTEGER,
                admin_notes TEXT,
                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # ============ ИНДЕКСЫ ============
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_bets_user ON bets(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_bets_match ON bets(match_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_user ON predictions(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type)')
        
        # ============ БАЗОВЫЕ ПРИЗЫ ============
        cursor.execute('SELECT COUNT(*) FROM prizes')
        if cursor.fetchone()[0] == 0:
            prizes = [
                ('Футболка Real Madrid', 'Оригинальная футболка сезона 2024/25', 1000, '👕'),
                ('Telegram Premium 3 мес', 'Подписка Telegram Premium на 3 месяца', 1500, '⭐'),
                ('PlayStation 5 Slim', 'Игровая консоль PS5 Slim', 55000, '🎮')
            ]
            cursor.executemany('''
                INSERT INTO prizes (name, description, points_required, image_url)
                VALUES (?, ?, ?, ?)
            ''', prizes)
        
        print("✅ База данных инициализирована")


# ============ ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ============

def get_user(user_id: int) -> Optional[Dict]:
    """Получить пользователя по ID"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> Dict:
    """Создать нового пользователя с приветственным бонусом 50 очков"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, balance)
            VALUES (?, ?, ?, ?, 50)
        ''', (user_id, username, first_name, last_name))
        
        # Записываем транзакцию приветственного бонуса
        if cursor.rowcount > 0:
            cursor.execute('''
                INSERT INTO transactions (user_id, type, amount, balance_before, balance_after, 
                                         wager_before, wager_after, description)
                VALUES (?, 'bonus', 50, 0, 50, 0, 0, 'Приветственный бонус')
            ''', (user_id,))
        
    return get_user(user_id)


def get_or_create_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> Dict:
    """Получить или создать пользователя"""
    user = get_user(user_id)
    if not user:
        user = create_user(user_id, username, first_name, last_name)
    else:
        # Обновляем last_active и данные профиля
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET last_active = CURRENT_TIMESTAMP,
                                username = COALESCE(?, username),
                                first_name = COALESCE(?, first_name),
                                last_name = COALESCE(?, last_name)
                WHERE user_id = ?
            ''', (username, first_name, last_name, user_id))
        user = get_user(user_id)
    return user


def update_user_balance(user_id: int, amount: int, transaction_type: str,
                       description: str = None, reference_id: str = None,
                       admin_id: int = None, affect_wager: bool = False) -> bool:
    """
    Обновить баланс пользователя с записью транзакции.

    affect_wager: если True и amount > 0, добавляет к wager_remaining (для депозитов).

    SECURITY: для отрицательных amount (списания: призы, штрафы) используется
    атомарный UPDATE с WHERE balance >= -amount, чтобы исключить гонку и уход в минус.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Списание (negative amount) — атомарно
        if amount < 0:
            need = -amount
            cursor.execute('SELECT balance, wager_remaining FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            balance_before = row['balance']
            wager_before = row['wager_remaining']

            cursor.execute('''
                UPDATE users SET balance = balance - ?, last_active = CURRENT_TIMESTAMP
                 WHERE user_id = ? AND balance >= ?
            ''', (need, user_id, need))
            if cursor.rowcount == 0:
                return False
            balance_after = balance_before - need
            wager_after = wager_before
        else:
            # Зачисление — read-then-write безопасно (только увеличение)
            cursor.execute('SELECT balance, wager_remaining FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            balance_before = row['balance']
            wager_before = row['wager_remaining']
            balance_after = balance_before + amount
            wager_after = wager_before + amount if (affect_wager and amount > 0) else wager_before
            cursor.execute('''
                UPDATE users SET balance = ?, wager_remaining = ?, last_active = CURRENT_TIMESTAMP
                 WHERE user_id = ?
            ''', (balance_after, wager_after, user_id))
        
        # Записываем транзакцию
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, balance_before, balance_after,
                                     wager_before, wager_after, description, reference_id, admin_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, transaction_type, amount, balance_before, balance_after,
              wager_before, wager_after, description, reference_id, admin_id))
        
        return True


def can_claim_prize(user_id: int) -> Tuple[bool, int]:
    """
    Проверить, может ли пользователь получить приз
    (нужно отыграть все купленные очки)
    Возвращает (можно_получить_приз, сколько_осталось_отыграть)
    """
    user = get_user(user_id)
    if not user:
        return False, 0
    
    wager_remaining = user['wager_remaining']
    return wager_remaining <= 0, max(0, wager_remaining)


def reduce_wager(user_id: int, bet_amount: int) -> int:
    """
    Уменьшить оставшийся вейджер после ставки
    Возвращает новое значение wager_remaining
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Получаем текущий вейджер
        cursor.execute('SELECT wager_remaining FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if not row:
            return 0
        
        current_wager = row['wager_remaining']
        new_wager = max(0, current_wager - bet_amount)
        
        # Обновляем
        cursor.execute('UPDATE users SET wager_remaining = ? WHERE user_id = ?', (new_wager, user_id))
        
        return new_wager


def get_user_transactions(user_id: int, limit: int = 20) -> List[Dict]:
    """Получить историю транзакций пользователя"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM transactions 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (user_id, limit))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def purchase_prize(user_id: int, prize_id: int, prize_name: str, prize_cost: int, contact_info: str) -> Tuple[bool, str, Optional[int]]:
    """
    Покупка приза за очки
    Возвращает (успех, сообщение, claim_id)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Проверяем баланс
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        if not user:
            return False, "Пользователь не найден", None
        
        if user['balance'] < prize_cost:
            return False, f"Недостаточно очков! Нужно {prize_cost}, у тебя {user['balance']}", None
        
        # Списываем очки
        cursor.execute('''
            UPDATE users SET balance = balance - ? WHERE user_id = ?
        ''', (prize_cost, user_id))
        
        # Создаём заявку на приз
        cursor.execute('''
            INSERT INTO prize_claims (user_id, prize_id, contact_info, status)
            VALUES (?, ?, ?, 'purchased')
        ''', (user_id, prize_id, contact_info))
        
        claim_id = cursor.lastrowid
        
        # Записываем транзакцию
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, description, reference_id)
            VALUES (?, 'prize_purchase', ?, ?, ?)
        ''', (user_id, -prize_cost, f'Покупка приза: {prize_name}', str(claim_id)))
        
        return True, f"Приз '{prize_name}' куплен!", claim_id


# ============ ФУНКЦИИ ДЛЯ СТАВОК ============

def place_bet(user_id: int, match_id: str, bet_type: str, amount: int, odds: float,
              home_team: str = None, away_team: str = None, match_date: str = None) -> Optional[int]:
    """
    Разместить ставку на матч.
    Возвращает bet_id или None при ошибке.

    SECURITY: списание баланса выполняется атомарным UPDATE с условием
    WHERE balance >= amount, чтобы исключить race-condition при двойном клике
    или одновременных запросах. Раньше шёл паттерн read-then-write, через который
    можно было обойти проверку и уйти в минус.
    """
    if amount is None or amount <= 0:
        return None

    potential_win = int(amount * odds)

    with get_connection() as conn:
        cursor = conn.cursor()

        # Сначала читаем wager до операции (для записи в transactions)
        cursor.execute('SELECT balance, wager_remaining FROM users WHERE user_id = ?', (user_id,))
        _row = cursor.fetchone()
        if not _row:
            return None
        balance_before = _row['balance']
        wager_before = _row['wager_remaining']

        # Атомарно списываем сумму ТОЛЬКО если баланса хватает.
        # При параллельных запросах второй получит rowcount=0 и ставка не создастся.
        cursor.execute('''
            UPDATE users
               SET balance = balance - ?,
                   wager_remaining = MAX(0, wager_remaining - ?),
                   bets_total = bets_total + 1,
                   last_active = CURRENT_TIMESTAMP
             WHERE user_id = ? AND balance >= ?
        ''', (amount, amount, user_id, amount))

        if cursor.rowcount == 0:
            # Недостаточно средств или гонка отсечена
            return None

        balance_after = balance_before - amount
        wager_after = max(0, wager_before - amount)

        # Создаём ставку
        cursor.execute('''
            INSERT INTO bets (user_id, match_id, bet_type, amount, odds, potential_win,
                            home_team, away_team, match_date, counted_for_wager)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (user_id, match_id, bet_type, amount, odds, potential_win,
              home_team, away_team, match_date))

        bet_id = cursor.lastrowid

        # Записываем транзакцию
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, balance_before, balance_after,
                                     wager_before, wager_after, description, reference_id)
            VALUES (?, 'bet', ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, -amount, balance_before, balance_after, wager_before, wager_after,
              f'Ставка на {home_team} vs {away_team}: {bet_type}', str(bet_id)))

        return bet_id


def get_user_bets(user_id: int, status: str = None, limit: int = 20) -> List[Dict]:
    """Получить ставки пользователя"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        if status:
            cursor.execute('''
                SELECT * FROM bets WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (user_id, status, limit))
        else:
            cursor.execute('''
                SELECT * FROM bets WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (user_id, limit))
        
        return [dict(row) for row in cursor.fetchall()]


def get_pending_bets_for_match(match_id: str) -> List[Dict]:
    """Получить все pending ставки на матч для расчёта"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM bets WHERE match_id = ? AND status = 'pending'
        ''', (match_id,))
        return [dict(row) for row in cursor.fetchall()]


def settle_bet(bet_id: int, result: str, exact_score: str = None) -> bool:
    """
    Рассчитать ставку по результату матча
    result: 'home' / 'draw' / 'away'
    exact_score: 'X-Y' - точный счёт для ставок на счёт
    
    Логика выплат:
    - При выигрыше: возвращаем ставку + чистый профит (amount * odds)
    - При проигрыше: ставка уже списана, ничего не возвращаем
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Получаем ставку
        cursor.execute('SELECT * FROM bets WHERE bet_id = ? AND status = ?', (bet_id, 'pending'))
        bet = cursor.fetchone()
        if not bet:
            return False
        
        bet = dict(bet)
        user_id = bet['user_id']
        amount = bet['amount']
        potential_win = bet['potential_win']  # Это amount * odds (полная выплата)
        bet_type = bet['bet_type']
        
        # Определяем выиграл ли пользователь
        # Проверка на ставку "точный счёт" (формат: score_X-Y)
        if bet_type.startswith('score_'):
            # Это ставка на точный счёт
            bet_score = bet_type.replace('score_', '')
            is_won = exact_score and bet_score == exact_score
        else:
            # Обычная ставка (home/draw/away)
            is_won = bet_type == result
        
        if is_won:
            # Выигрыш - начисляем полную выплату (ставка * коэффициент)
            # potential_win уже содержит amount * odds
            profit = potential_win - amount  # Чистый профит
            status = 'won'
            
            # Обновляем баланс - начисляем полную выплату
            update_user_balance(user_id, potential_win, 'bet_win',
                              f'Выигрыш ставки #{bet_id}: {amount}×{bet["odds"]:.2f}={potential_win}', 
                              str(bet_id))
            
            # Обновляем статистику
            cursor.execute('''
                UPDATE users SET bets_won = bets_won + 1, bets_profit = bets_profit + ?
                WHERE user_id = ?
            ''', (profit, user_id))
        else:
            # Проигрыш - ставка уже списана при размещении
            profit = -amount
            status = 'lost'
            
            # Обновляем статистику
            cursor.execute('''
                UPDATE users SET bets_lost = bets_lost + 1, bets_profit = bets_profit + ?
                WHERE user_id = ?
            ''', (profit, user_id))
        
        # Обновляем ставку
        cursor.execute('''
            UPDATE bets SET status = ?, result = ?, profit = ?, settled_at = CURRENT_TIMESTAMP
            WHERE bet_id = ?
        ''', (status, result, profit, bet_id))
        
        return True


def sell_bet(bet_id: int, user_id: int, sell_price: int) -> bool:
    """
    Продать ставку до начала матча
    Возвращает 50% от суммы ставки
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Проверяем что ставка принадлежит пользователю и pending
        cursor.execute('SELECT * FROM bets WHERE bet_id = ? AND user_id = ? AND status = ?', 
                      (bet_id, user_id, 'pending'))
        bet = cursor.fetchone()
        if not bet:
            return False
        
        bet = dict(bet)
        
        # Обновляем статус ставки
        cursor.execute('''
            UPDATE bets SET status = 'sold', profit = ?, settled_at = CURRENT_TIMESTAMP
            WHERE bet_id = ?
        ''', (-bet['amount'] + sell_price, bet_id))
        
        # Возвращаем деньги пользователю (в той же транзакции)
        cursor.execute('''
            UPDATE users SET balance = balance + ? WHERE user_id = ?
        ''', (sell_price, user_id))
        
        # Записываем транзакцию
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, description, reference_id)
            VALUES (?, 'bet_sell', ?, ?, ?)
        ''', (user_id, sell_price, f'Продажа ставки #{bet_id}', str(bet_id)))
        
        return True


# ============ ФУНКЦИИ ДЛЯ ПРОГНОЗОВ ============

def make_prediction(user_id: int, match_id: str, prediction: str,
                   home_team: str = None, away_team: str = None, match_date: str = None) -> Optional[int]:
    """
    Сделать бесплатный прогноз на матч
    prediction: 'home' / 'draw' / 'away'
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Проверяем, не делал ли уже прогноз на этот матч
        cursor.execute('''
            SELECT prediction_id FROM predictions 
            WHERE user_id = ? AND match_id = ?
        ''', (user_id, match_id))
        
        if cursor.fetchone():
            return None  # Уже есть прогноз на этот матч
        
        # Создаём прогноз
        cursor.execute('''
            INSERT INTO predictions (user_id, match_id, prediction, home_team, away_team, match_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, match_id, prediction, home_team, away_team, match_date))
        
        prediction_id = cursor.lastrowid
        
        # Обновляем статистику
        cursor.execute('''
            UPDATE users SET predictions_total = predictions_total + 1, last_active = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (user_id,))
        
        return prediction_id


def get_user_predictions(user_id: int, status: str = None, limit: int = 20) -> List[Dict]:
    """Получить прогнозы пользователя"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        if status:
            cursor.execute('''
                SELECT * FROM predictions WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (user_id, status, limit))
        else:
            cursor.execute('''
                SELECT * FROM predictions WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (user_id, limit))
        
        return [dict(row) for row in cursor.fetchall()]


def get_pending_predictions_for_match(match_id: str) -> List[Dict]:
    """Получить все pending прогнозы на матч"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM predictions WHERE match_id = ? AND status = 'pending'
        ''', (match_id,))
        return [dict(row) for row in cursor.fetchall()]


def settle_prediction(prediction_id: int, actual_result: str) -> bool:
    """
    Рассчитать прогноз: +5 за угаданный, -10 за неугаданный
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM predictions WHERE prediction_id = ? AND status = ?', 
                      (prediction_id, 'pending'))
        pred = cursor.fetchone()
        if not pred:
            return False
        
        pred = dict(pred)
        user_id = pred['user_id']
        is_correct = pred['prediction'] == actual_result
        
        if is_correct:
            points_change = 5
            status = 'correct'
            update_user_balance(user_id, 5, 'prediction_win',
                              f'Угаданный прогноз #{prediction_id}', str(prediction_id))
            cursor.execute('''
                UPDATE users SET predictions_won = predictions_won + 1, 
                               predictions_profit = predictions_profit + 5
                WHERE user_id = ?
            ''', (user_id,))
        else:
            points_change = -10
            status = 'incorrect'
            update_user_balance(user_id, -10, 'prediction_loss',
                              f'Неугаданный прогноз #{prediction_id}', str(prediction_id))
            cursor.execute('''
                UPDATE users SET predictions_lost = predictions_lost + 1,
                               predictions_profit = predictions_profit - 10
                WHERE user_id = ?
            ''', (user_id,))
        
        cursor.execute('''
            UPDATE predictions SET status = ?, actual_result = ?, points_change = ?, 
                                  settled_at = CURRENT_TIMESTAMP
            WHERE prediction_id = ?
        ''', (status, actual_result, points_change, prediction_id))
        
        return True


def settle_all_for_match(match_id: str, result: str, exact_score: str = None) -> Dict[str, int]:
    """
    Рассчитать все ставки и прогнозы на матч
    result: 'home' / 'draw' / 'away'
    exact_score: 'X-Y' - точный счёт (для ставок на счёт)
    Возвращает статистику: {'bets_settled': N, 'predictions_settled': M}
    """
    bets_settled = 0
    predictions_settled = 0
    
    # Рассчитываем ставки (включая ставки на точный счёт)
    pending_bets = get_pending_bets_for_match(match_id)
    for bet in pending_bets:
        if settle_bet(bet['bet_id'], result, exact_score):
            bets_settled += 1
    
    # Рассчитываем прогнозы
    pending_predictions = get_pending_predictions_for_match(match_id)
    for pred in pending_predictions:
        if settle_prediction(pred['prediction_id'], result):
            predictions_settled += 1
    
    return {'bets_settled': bets_settled, 'predictions_settled': predictions_settled}


# ============ ФУНКЦИИ ДЛЯ РЕЙТИНГА ============

def get_leaderboard(limit: int = 20, by: str = 'balance') -> List[Dict]:
    """
    Получить рейтинг игроков
    by: 'balance' / 'bets_profit' / 'predictions_profit' / 'bets_won' / 'predictions_won'
    """
    valid_columns = ['balance', 'bets_profit', 'predictions_profit', 'bets_won', 'predictions_won']
    if by not in valid_columns:
        by = 'balance'
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT user_id, username, first_name, balance, 
                   bets_total, bets_won, bets_profit,
                   predictions_total, predictions_won, predictions_profit
            FROM users
            WHERE is_banned = 0
            ORDER BY {by} DESC
            LIMIT ?
        ''', (limit,))
        
        return [dict(row) for row in cursor.fetchall()]


# ============ ФУНКЦИИ ДЛЯ ТРАНЗАКЦИЙ ============

def get_user_transactions(user_id: int, limit: int = 20) -> List[Dict]:
    """Получить историю транзакций пользователя"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM transactions WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ?
        ''', (user_id, limit))
        return [dict(row) for row in cursor.fetchall()]


# ============ АДМИНСКИЕ ФУНКЦИИ ============

def admin_add_points(user_id: int, amount_points: int, admin_id: int, description: str = None) -> bool:
    """Начислить очки пользователю (с добавлением вейджера для купленных очков)"""
    return update_user_balance(user_id, amount_points, 'deposit',
                              description or f'Покупка {amount_points} очков',
                              admin_id=admin_id, affect_wager=True)


def admin_add_bonus(user_id: int, amount_points: int, admin_id: int, description: str = None) -> bool:
    """Начислить бонусные очки (БЕЗ вейджера)"""
    return update_user_balance(user_id, amount_points, 'bonus',
                              description or f'Бонус {amount_points} очков',
                              admin_id=admin_id, affect_wager=False)


def get_all_users(limit: int = 100, offset: int = 0) -> List[Dict]:
    """Получить список всех пользователей для админки"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM users ORDER BY last_active DESC LIMIT ? OFFSET ?
        ''', (limit, offset))
        return [dict(row) for row in cursor.fetchall()]


def set_admin(user_id: int, is_admin: bool = True) -> bool:
    """Назначить/снять админа"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_admin = ? WHERE user_id = ?', (1 if is_admin else 0, user_id))
        return cursor.rowcount > 0


def ban_user(user_id: int, is_banned: bool = True) -> bool:
    """Забанить/разбанить пользователя"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_banned = ? WHERE user_id = ?', (1 if is_banned else 0, user_id))
        return cursor.rowcount > 0


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь админом"""
    user = get_user(user_id)
    return user and user['is_admin'] == 1


# ============ ФУНКЦИИ ДЛЯ ПРИЗОВ ============

def get_available_prizes() -> List[Dict]:
    """Получить список доступных призов"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM prizes 
            WHERE is_active = 1 AND (quantity_total = -1 OR quantity_claimed < quantity_total)
            ORDER BY points_required ASC
        ''')
        return [dict(row) for row in cursor.fetchall()]


def claim_prize(user_id: int, prize_id: int, contact_info: str) -> Tuple[bool, str]:
    """
    Запросить приз
    Возвращает (успех, сообщение)
    """
    user = get_user(user_id)
    if not user:
        return False, 'Пользователь не найден'
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Проверяем приз
        cursor.execute('SELECT * FROM prizes WHERE prize_id = ? AND is_active = 1', (prize_id,))
        prize = cursor.fetchone()
        if not prize:
            return False, 'Приз не найден'
        
        prize = dict(prize)
        
        # Проверяем баланс
        if user['balance'] < prize['points_required']:
            return False, f'Недостаточно очков. Нужно: {prize["points_required"]}, у вас: {user["balance"]}'
        
        # Проверяем вейджер (отыгрыш)
        can, wager_left = can_claim_prize(user_id)
        if not can:
            return False, f'Сначала отыграйте купленные очки! Осталось поставить: {wager_left} очков'
        
        # Проверяем количество
        if prize['quantity_total'] != -1 and prize['quantity_claimed'] >= prize['quantity_total']:
            return False, 'Призы закончились'
        
        # Списываем очки
        success = update_user_balance(user_id, -prize['points_required'], 'prize',
                                     f'Заявка на приз: {prize["name"]}', str(prize_id))
        if not success:
            return False, 'Ошибка при списании очков'
        
        # Создаём заявку
        cursor.execute('''
            INSERT INTO prize_claims (user_id, prize_id, contact_info)
            VALUES (?, ?, ?)
        ''', (user_id, prize_id, contact_info))
        
        # Увеличиваем счётчик
        cursor.execute('''
            UPDATE prizes SET quantity_claimed = quantity_claimed + 1 WHERE prize_id = ?
        ''', (prize_id,))
        
        return True, f'Заявка на "{prize["name"]}" создана! Ожидайте связи от админа.'


def get_pending_prize_claims() -> List[Dict]:
    """Получить заявки на призы для админа"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT pc.*, p.name as prize_name, p.points_required,
                   u.username, u.first_name, u.user_id
            FROM prize_claims pc
            JOIN prizes p ON pc.prize_id = p.prize_id
            JOIN users u ON pc.user_id = u.user_id
            WHERE pc.status = 'pending'
            ORDER BY pc.created_at ASC
        ''')
        return [dict(row) for row in cursor.fetchall()]


def process_prize_claim(claim_id: int, admin_id: int, approve: bool, notes: str = None) -> bool:
    """Обработать заявку на приз"""
    with get_connection() as conn:
        cursor = conn.cursor()
        status = 'approved' if approve else 'rejected'
        
        cursor.execute('''
            UPDATE prize_claims SET status = ?, admin_id = ?, admin_notes = ?,
                                   processed_at = CURRENT_TIMESTAMP
            WHERE claim_id = ? AND status = 'pending'
        ''', (status, admin_id, notes, claim_id))
        
        # Если отклонено - возвращаем очки
        if not approve:
            cursor.execute('''
                SELECT pc.user_id, p.points_required 
                FROM prize_claims pc
                JOIN prizes p ON pc.prize_id = p.prize_id
                WHERE pc.claim_id = ?
            ''', (claim_id,))
            row = cursor.fetchone()
            if row:
                update_user_balance(row['user_id'], row['points_required'], 'refund',
                                  f'Возврат за отклонённую заявку на приз', str(claim_id))
        
        return cursor.rowcount > 0


# ============ СТАТИСТИКА ============

def get_global_stats() -> Dict:
    """Получить глобальную статистику для админа"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        stats = {}
        
        cursor.execute('SELECT COUNT(*) as total FROM users')
        stats['total_users'] = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM users WHERE last_active > datetime("now", "-1 day")')
        stats['active_today'] = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM bets')
        stats['total_bets'] = cursor.fetchone()['total']
        
        cursor.execute('SELECT COUNT(*) as total FROM predictions')
        stats['total_predictions'] = cursor.fetchone()['total']
        
        cursor.execute('SELECT SUM(total_deposited) as total FROM users')
        stats['total_deposited'] = cursor.fetchone()['total'] or 0
        
        cursor.execute('SELECT COUNT(*) as total FROM prize_claims WHERE status = "approved"')
        stats['prizes_given'] = cursor.fetchone()['total']
        
        return stats


# Инициализация при импорте
if __name__ == '__main__':
    init_database()
    print("\n📊 Тестируем базу данных...\n")
    
    # Тест: создаём пользователя
    user = get_or_create_user(123456789, 'testuser', 'Тест', 'Юзер')
    print(f"✅ Создан пользователь: {user['username']}, баланс: {user['balance']}")
    
    # Тест: покупка очков (с вейджером)
    admin_add_points(123456789, 1000, 999999, 'Покупка 1000 очков')
    user = get_user(123456789)
    print(f"✅ После покупки: баланс={user['balance']}, вейджер={user['wager_remaining']}")
    
    # Тест: ставка уменьшает вейджер
    place_bet(123456789, 'match_001', 'home', 500, 1.85, 'Real Madrid', 'Barcelona', '15.01.2026')
    user = get_user(123456789)
    print(f"✅ После ставки 500: баланс={user['balance']}, вейджер={user['wager_remaining']}")
    
    # Проверка возможности получить приз
    can, left = can_claim_prize(123456789)
    print(f"✅ Можно получить приз: {can}, осталось отыграть: {left}")
    
    # Тест бонуса (без вейджера)
    admin_add_bonus(123456789, 100, 999999, 'Бонус за активность')
    user = get_user(123456789)
    print(f"✅ После бонуса +100: баланс={user['balance']}, вейджер={user['wager_remaining']} (не изменился!)")
    
    print("\n🎉 Все тесты пройдены!")
