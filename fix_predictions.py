#!/usr/bin/env python3
"""
Script to check and fix pending predictions
Run on server: python3 fix_predictions.py
"""

import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', 'bot.db')

def fix_predictions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=" * 50)
    print("CHECKING PREDICTIONS")
    print("=" * 50)
    
    # Get all predictions
    cursor.execute('SELECT * FROM predictions ORDER BY created_at DESC LIMIT 20')
    predictions = cursor.fetchall()
    
    print(f"\nTotal predictions found: {len(predictions)}\n")
    
    for p in predictions:
        print(f"ID: {p['prediction_id']}")
        print(f"  User: {p['user_id']}")
        print(f"  Match ID: {p['match_id']}")
        print(f"  Match: {p['home_team']} vs {p['away_team']}")
        print(f"  Date: {p['match_date']}")
        print(f"  Prediction: {p['prediction']}")
        print(f"  Status: {p['status']}")
        print(f"  Actual result: {p['actual_result']}")
        print("-" * 40)
    
    # Check pending predictions that might need settling
    cursor.execute('''
        SELECT * FROM predictions 
        WHERE status = 'pending' 
        AND match_date < datetime('now')
    ''')
    old_pending = cursor.fetchall()
    
    if old_pending:
        print(f"\n⚠️ Found {len(old_pending)} pending predictions for past matches!")
        print("These should be settled.\n")
        
        for p in old_pending:
            print(f"  - {p['home_team']} vs {p['away_team']} ({p['match_date']})")
            print(f"    Prediction: {p['prediction']}, Status: {p['status']}")
    
    conn.close()

def settle_prediction_manually(prediction_id: int, actual_result: str):
    """
    Manually settle a prediction
    actual_result: 'home', 'draw', 'away'
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get prediction
    cursor.execute('SELECT * FROM predictions WHERE prediction_id = ?', (prediction_id,))
    pred = cursor.fetchone()
    
    if not pred:
        print(f"Prediction {prediction_id} not found!")
        return
    
    # Determine win/loss
    won = pred[4] == actual_result  # prediction column
    status = 'won' if won else 'lost'
    points_change = 50 if won else 0  # Reward for correct prediction
    
    # Update prediction
    cursor.execute('''
        UPDATE predictions 
        SET status = ?, actual_result = ?, points_change = ?, settled_at = CURRENT_TIMESTAMP
        WHERE prediction_id = ?
    ''', (status, actual_result, points_change, prediction_id))
    
    # Update user balance and stats if won
    if won:
        cursor.execute('''
            UPDATE users 
            SET balance = balance + ?,
                predictions_won = predictions_won + 1
            WHERE user_id = ?
        ''', (points_change, pred[1]))  # user_id
        print(f"✅ Prediction {prediction_id} settled as WON! +{points_change} points")
    else:
        cursor.execute('''
            UPDATE users 
            SET predictions_lost = predictions_lost + 1
            WHERE user_id = ?
        ''', (pred[1],))
        print(f"❌ Prediction {prediction_id} settled as LOST")
    
    conn.commit()
    conn.close()

def settle_all_pending_for_match(match_identifier: str, actual_result: str):
    """
    Settle all pending predictions for a match
    match_identifier: can be match_id or part of team names
    actual_result: 'home', 'draw', 'away'
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Find predictions
    cursor.execute('''
        SELECT * FROM predictions 
        WHERE status = 'pending' 
        AND (match_id = ? OR home_team LIKE ? OR away_team LIKE ?)
    ''', (match_identifier, f'%{match_identifier}%', f'%{match_identifier}%'))
    
    predictions = cursor.fetchall()
    
    if not predictions:
        print(f"No pending predictions found for '{match_identifier}'")
        return
    
    print(f"Found {len(predictions)} pending predictions to settle:")
    
    for pred in predictions:
        won = pred['prediction'] == actual_result
        status = 'won' if won else 'lost'
        points_change = 50 if won else 0
        
        cursor.execute('''
            UPDATE predictions 
            SET status = ?, actual_result = ?, points_change = ?, settled_at = CURRENT_TIMESTAMP
            WHERE prediction_id = ?
        ''', (status, actual_result, points_change, pred['prediction_id']))
        
        if won:
            cursor.execute('''
                UPDATE users 
                SET balance = balance + ?,
                    predictions_won = predictions_won + 1
                WHERE user_id = ?
            ''', (points_change, pred['user_id']))
            print(f"  ✅ ID {pred['prediction_id']}: {pred['home_team']} vs {pred['away_team']} - WON (+{points_change})")
        else:
            cursor.execute('''
                UPDATE users 
                SET predictions_lost = predictions_lost + 1
                WHERE user_id = ?
            ''', (pred['user_id'],))
            print(f"  ❌ ID {pred['prediction_id']}: {pred['home_team']} vs {pred['away_team']} - LOST")
    
    conn.commit()
    conn.close()
    print(f"\n✅ Settled {len(predictions)} predictions!")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) == 1:
        fix_predictions()
    elif len(sys.argv) == 3:
        # Usage: python fix_predictions.py "Atletico" "away"
        settle_all_pending_for_match(sys.argv[1], sys.argv[2])
    else:
        print("Usage:")
        print("  python fix_predictions.py                    - Check all predictions")
        print("  python fix_predictions.py 'Atletico' 'away'  - Settle predictions for match")
