"""src/shared/streams_io.py — streams.json reader."""
import os
import json

STREAMS_FILE = '/app/data/streams.json'


def get_streams_data():
    """Получить данные стримов"""
    try:
        if os.path.exists(STREAMS_FILE):
            with open(STREAMS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"streams": [], "updated": "", "updated_by": ""}
