"""src/parsers/news.py — News scraper for fondoruso.ru.

Парсер новостей Real Madrid с сайта fondoruso.ru:
- scrape_news_list(count) — список новостей с превью
- scrape_article(url) — полный текст статьи с изображениями

Кэши:
- _news_scrape_cache — список новостей, TTL 15 минут
- _article_cache — отдельные статьи, TTL 1 час

См. Obsidian/Real Madrid/01 - Frontend/Pages/Новости.md
"""
import time as _t
import requests
from bs4 import BeautifulSoup

# === Configuration ===
NEWS_SOURCE_URL = "https://fondoruso.ru/news/"
NEWS_SCRAPE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
NEWS_SCRAPE_TTL = 900  # 15 minutes
ARTICLE_TTL = 3600  # 1 hour

# === Caches (singleton) ===
_news_scrape_cache = {'data': [], 'time': 0}
_article_cache = {}


def scrape_news_list(count=20):
    """Scrape news from fondoruso.ru. Returns up to `count` items, newest first.

    Each item: {id, title, description, image, date, tag, link}.
    On error: returns cached data if any, else [].
    """
    now = _t.time()

    if _news_scrape_cache['data'] and (now - _news_scrape_cache['time']) < NEWS_SCRAPE_TTL:
        return _news_scrape_cache['data'][:count]

    try:
        resp = requests.get(NEWS_SOURCE_URL, headers=NEWS_SCRAPE_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        news = []
        articles = soup.select('li.news-mini__item')

        for art in articles[:count]:
            link_el = art.select_one('a.news-mini__link')
            href = link_el.get('href', '') if link_el else ''
            if href and not href.startswith('http'):
                href = 'https://fondoruso.ru/' + href.lstrip('/')

            title_el = art.select_one('h3.news-mini__title')
            title = title_el.get_text(strip=True) if title_el else ''

            img_el = art.select_one('img.news-mini__img')
            image = ''
            if img_el:
                image = img_el.get('data-src', '') or img_el.get('src', '')
                if image and not image.startswith('http'):
                    image = 'https://fondoruso.ru' + image

            desc_el = art.select_one('.news-mini__text-preview')
            description = desc_el.get_text(strip=True)[:200] if desc_el else ''

            date_el = art.select_one('.info__item--date')
            date_text = date_el.get_text(strip=True) if date_el else ''

            tag_el = art.select_one('.tag')
            tag = tag_el.get_text(strip=True) if tag_el else ''

            if title:
                slug = href.rstrip('/').split('/')[-1] if href else str(len(news))
                news.append({
                    'id': slug,
                    'title': title,
                    'description': description,
                    'image': image,
                    'date': date_text,
                    'tag': tag,
                    'link': href,
                })

        _news_scrape_cache['data'] = news
        _news_scrape_cache['time'] = now
        print(f"Scraped {len(news)} news from fondoruso.ru", flush=True)
        return news[:count]

    except Exception as e:
        print(f"News scrape error: {e}", flush=True)
        return _news_scrape_cache.get('data', [])[:count]


def scrape_article(url):
    """Scrape full article body + images from fondoruso.ru URL.

    Returns: {title, date, paragraphs: [...], images: [...]} or None on error.
    Cache per URL, TTL 1 hour.
    """
    if url in _article_cache:
        cached = _article_cache[url]
        if _t.time() - cached['time'] < ARTICLE_TTL:
            return cached['data']

    try:
        resp = requests.get(url, headers=NEWS_SCRAPE_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        title_el = soup.select_one('h1.heading')
        title = title_el.get_text(strip=True) if title_el else ''

        date_el = soup.select_one('.info__item--date')
        date = date_el.get_text(strip=True) if date_el else ''

        main_img_el = soup.select_one('.news__img')
        main_image = ''
        if main_img_el:
            main_image = main_img_el.get('data-src', '') or main_img_el.get('src', '')
            if main_image and not main_image.startswith('http'):
                main_image = 'https://fondoruso.ru/' + main_image.lstrip('/')

        body_el = soup.select_one('.news__text')
        paragraphs = []
        images = []

        # NOTE: main_image добавляется только в images[], НЕ в content.
        # Frontend ArticleView отдельно рендерит главное фото из e.image (карточки списка),
        # дублирование в content вызывает повтор картинки на странице статьи.
        if main_image:
            images.append(main_image)

        if body_el:
            for tag in body_el.select('script, style, .adzone-container, .adzone-iframe-box, iframe, .adzone-banner'):
                tag.decompose()

            for el in body_el.children:
                if hasattr(el, 'name'):
                    if el.name == 'p':
                        text = el.get_text(strip=True)
                        if text:
                            paragraphs.append(text)
                        for img in el.select('img'):
                            src = img.get('data-src', '') or img.get('src', '')
                            if src:
                                if not src.startswith('http'):
                                    src = 'https://fondoruso.ru/' + src.lstrip('/')
                                images.append(src)
                                paragraphs.append(f'[IMG]{src}[/IMG]')
                    elif el.name == 'img':
                        src = el.get('data-src', '') or el.get('src', '')
                        if src:
                            if not src.startswith('http'):
                                src = 'https://fondoruso.ru/' + src.lstrip('/')
                            images.append(src)
                            paragraphs.append(f'[IMG]{src}[/IMG]')
                    elif el.name in ('h2', 'h3', 'h4'):
                        text = el.get_text(strip=True)
                        if text:
                            paragraphs.append(f'**{text}**')
                    elif el.name == 'ul':
                        for li in el.select('li'):
                            text = li.get_text(strip=True)
                            if text:
                                paragraphs.append(f'• {text}')
                    elif el.name == 'blockquote':
                        text = el.get_text(strip=True)
                        if text:
                            paragraphs.append(f'> {text}')

        result = {
            'title': title,
            'date': date,
            'content': paragraphs,   # frontend ArticleView reads t.content
            'images': images,
            'link': url,             # frontend "Открыть на сайте" button
        }
        _article_cache[url] = {'data': result, 'time': _t.time()}
        return result

    except Exception as e:
        print(f"Article scrape error: {e}", flush=True)
        return None
