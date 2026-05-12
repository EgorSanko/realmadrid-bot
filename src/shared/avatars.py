"""src/shared/avatars.py — Telegram avatar fetch + cleanup helpers.

State:
- _user_photos: user_id → True if downloaded
- _user_photos_fetched: set of user_ids we already tried (avoid retries)
- _AVATAR_DIR: filesystem path

Functions:
- _fetch_and_save_avatar(user_id): downloads via Bot API getUserProfilePhotos→getFile
- cleanup_old_photos(): deletes /app/data/photos older than 1h, videos older than 2h
"""
import os
import time as _time
import requests


# BOT_TOKEN imported lazily inside _fetch_and_save_avatar to avoid env race


_user_photos = {}
_user_photos_fetched = set()  # Track which users we already tried to fetch
_AVATAR_DIR = '/app/data/avatars'

def _fetch_and_save_avatar(user_id: int) -> bool:
    """Download user avatar via Telegram Bot API and save locally"""
    from api import BOT_TOKEN
    try:
        os.makedirs(_AVATAR_DIR, exist_ok=True)
        avatar_path = f"{_AVATAR_DIR}/{user_id}.jpg"

        # Skip if already exists and fresh (less than 24h)
        if os.path.exists(avatar_path):
            age = _time.time() - os.path.getmtime(avatar_path)
            if age < 86400:  # 24 hours
                return True

        # Get user profile photos
        resp = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos",
            params={"user_id": user_id, "limit": 1},
            timeout=5
        )
        data = resp.json()
        if not data.get('ok') or not data.get('result', {}).get('photos'):
            return False

        # Get medium size photo
        photo_sizes = data['result']['photos'][0]
        size = photo_sizes[min(1, len(photo_sizes)-1)]
        file_id = size['file_id']

        # Get file path
        resp2 = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=5
        )
        data2 = resp2.json()
        if not data2.get('ok'):
            return False

        file_path = data2['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

        # Download and save
        img_resp = requests.get(file_url, timeout=10)
        if img_resp.status_code == 200:
            with open(avatar_path, 'wb') as f:
                f.write(img_resp.content)
            return True
        return False
    except Exception as e:
        print(f"Avatar fetch error for {user_id}: {e}", flush=True)
        return False


async def cleanup_old_photos():
    """Удалить старые медиа файлы"""
    import time
    import time; now = time.time()

    # Очистка фото (старше 1 часа)
    photo_dir = '/app/data/photos'
    if os.path.exists(photo_dir):
        for filename in os.listdir(photo_dir):
            filepath = os.path.join(photo_dir, filename)
            try:
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > 3600:  # 1 час
                        os.remove(filepath)
                        print(f"Deleted old photo: {filename}")
            except Exception as e:
                print(f"Cleanup error: {e}")

    # Очистка видео (старше 2 часов)
    video_dir = '/app/data/videos'
    if os.path.exists(video_dir):
        for filename in os.listdir(video_dir):
            filepath = os.path.join(video_dir, filename)
            try:
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > 7200:  # 2 часа
                        os.remove(filepath)
                        print(f"Deleted old video: {filename}")
            except Exception as e:
                print(f"Video cleanup error: {e}")
