"""src/routes/files.py — Static file serving (photo, video, avatar).

Эндпоинты:
- GET /api/photo/{filename} — фото матча
- GET /api/video/{filename} — видео highlights
- GET /api/avatar/{user_id} — аватарка юзера + on-demand fetch from Telegram
"""
import os
from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

router = APIRouter(prefix="/api", tags=["files"])

PHOTOS_DIR = '/app/data/photos'
VIDEOS_DIR = '/app/data/videos'

# 1x1 transparent PNG fallback for missing avatars
EMPTY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


def init():
    @router.get("/photo/{filename}")
    async def get_photo(filename: str):
        path = f'{PHOTOS_DIR}/{filename}'
        if os.path.exists(path):
            return FileResponse(path, media_type='image/jpeg')
        return {"error": "Photo not found"}

    @router.get("/video/{filename}")
    async def get_video(filename: str):
        path = f'{VIDEOS_DIR}/{filename}'
        if os.path.exists(path):
            return FileResponse(path, media_type='video/mp4')
        return {"error": "Video not found"}

    @router.get("/avatar/{user_id}")
    async def get_avatar(user_id: int):
        from api import _AVATAR_DIR, _fetch_and_save_avatar, _user_photos

        avatar_path = f"{_AVATAR_DIR}/{user_id}.jpg"
        if os.path.exists(avatar_path):
            return FileResponse(avatar_path, media_type='image/jpeg',
                                headers={"Cache-Control": "public, max-age=3600"})

        if _fetch_and_save_avatar(user_id) and os.path.exists(avatar_path):
            _user_photos[user_id] = True
            return FileResponse(avatar_path, media_type='image/jpeg',
                                headers={"Cache-Control": "public, max-age=3600"})

        return Response(content=EMPTY_PNG, media_type='image/png',
                        status_code=200, headers={"Cache-Control": "public, max-age=300"})
