#!/usr/bin/env python3
"""
Миграция: добавление реферальной системы
Запуск: docker exec rm-bot python3 /app/migrate_referral.py
"""

import sqlite3

DB_PATH = '/app/data/betting.db'

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Проверяем есть ли колонка referred_by
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'referred_by' not in columns:
        print("➕ Добавляю колонку referred_by...")
        cursor.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL")
        print("✅ Колонка referred_by добавлена")
    else:
        print("✅ Колонка referred_by уже существует")
    
    conn.commit()
    conn.close()
    print("✅ Миграция завершена!")

if __name__ == '__main__':
    migrate()
