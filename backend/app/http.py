import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

client = httpx.AsyncClient(
    headers={"User-Agent": UA, "Accept-Language": "en"},
    timeout=httpx.Timeout(8.0, connect=5.0),
    follow_redirects=True,
)


async def get_json(url: str, **params):
    r = await client.get(url, params=params or None)
    r.raise_for_status()
    return r.json()


async def get_text(url: str) -> str:
    r = await client.get(url)
    r.raise_for_status()
    return r.text
