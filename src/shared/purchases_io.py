"""src/shared/purchases_io.py — Purchase config + JSON store."""
import os
import json

PURCHASES_FILE = '/app/data/purchases.json'
RECEIPTS_DIR = '/app/data/receipts'
PURCHASE_CONFIG = {
    'card_number': '2202 2032 1091 8506',   # <-- ОБНОВИТЬ номер карты!
    'card_bank': 'Сбербанк',
    'price_per_point': 2.5,
    'min_purchase': 100,
    'amounts': [100, 250, 500, 1000],
}


def _load_purchases():
    try:
        if os.path.exists(PURCHASES_FILE):
            with open(PURCHASES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return []


def _save_purchases(data):
    with open(PURCHASES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
