#!/usr/bin/env python3
"""
Script to create missing tables in database
Run: python3 init_tables.py
"""

import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', 'bot.db')

def init_missing_tables():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("Checking and creating missing tables...")
    
    # Check existing tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing = [row[0] for row in cursor.fetchall()]
    print(f"Existing tables: {existing}")
    
    # Create predictions table if not exists
    if 'predictions' not in existing:
        print("\nCreating predictions table...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS predictions (
                prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                match_id TEXT NOT NULL,
                prediction TEXT NOT NULL,
                home_team TEXT,
                away_team TEXT,
                match_date TEXT,
                status TEXT DEFAULT 'pending',
                actual_result TEXT,
                points_change INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settled_at TIMESTAMP,
                
                UNIQUE(user_id, match_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_user ON predictions(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status)')
        print("✅ predictions table created!")
    else:
        print("✅ predictions table already exists")
    
    # Create transactions table if not exists
    if 'transactions' not in existing:
        print("\nCreating transactions table...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                description TEXT,
                reference_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)')
        print("✅ transactions table created!")
    else:
        print("✅ transactions table already exists")
    
    # Check users table has all columns
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row[1] for row in cursor.fetchall()]
    print(f"\nUsers table columns: {user_columns}")
    
    # Add missing columns to users
    missing_columns = [
        ('predictions_total', 'INTEGER DEFAULT 0'),
        ('predictions_won', 'INTEGER DEFAULT 0'),
        ('predictions_lost', 'INTEGER DEFAULT 0'),
        ('predictions_profit', 'INTEGER DEFAULT 0'),
        ('predictions_correct', 'INTEGER DEFAULT 0'),
    ]
    
    for col_name, col_type in missing_columns:
        if col_name not in user_columns:
            try:
                cursor.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_type}')
                print(f"✅ Added column {col_name} to users table")
            except Exception as e:
                print(f"Column {col_name}: {e}")
    
    conn.commit()
    conn.close()
    print("\n✅ Database initialization complete!")


if __name__ == '__main__':
    init_missing_tables()
