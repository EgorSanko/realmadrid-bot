"""Мадридиста — API. Этап 0: только проверка живости."""
from datetime import datetime, timezone

from fastapi import FastAPI

from app.stream import router as stream_router

VERSION = "0.1.0"

app = FastAPI(
    title="Мадридиста API",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(stream_router)


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health() -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "time": datetime.now(timezone.utc).isoformat(),
    }
