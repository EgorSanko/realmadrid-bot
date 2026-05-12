"""src/routes/news.py — News API endpoints.

Эндпоинты:
- GET /api/news — список новостей с превью
- GET /api/news/article?url=... — полный текст статьи

Использует src/parsers/news.py (scraping логика).

См. Obsidian/Real Madrid/01 - Frontend/Pages/Новости.md
"""
from fastapi import APIRouter

from src.parsers.news import scrape_news_list, scrape_article

router = APIRouter(prefix="/api", tags=["news"])


@router.get("/news")
async def get_news(count: int = 10):
    """Get news scraped from fondoruso.ru (cached 15 min)."""
    try:
        news = scrape_news_list(count=count)
        return {"news": news, "count": len(news)}
    except Exception as e:
        print(f"News endpoint error: {e}", flush=True)
        return {"news": [], "count": 0, "error": str(e)}


@router.get("/news/article")
async def get_article_endpoint(url: str):
    """Get full article content from fondoruso.ru. Only this domain whitelisted."""
    if not url.startswith("https://fondoruso.ru/"):
        return {"error": "Only fondoruso.ru articles supported"}
    try:
        data = scrape_article(url)
        if data:
            return data
        return {"error": "Failed to load article"}
    except Exception as e:
        print(f"Article endpoint error: {e}", flush=True)
        return {"error": str(e)}
