"""
Диагностика - что видит requests на странице liveball
"""

import re
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# Получаем зеркало
print("1. Получаем зеркало...")
resp = requests.get('https://liveball.website/', headers=HEADERS, timeout=10)
match = re.search(r'https://([a-z0-9]+)\.liveball\.([a-z]{2,})', resp.text)
mirror = match.group(0) if match else None
print(f"   Зеркало: {mirror}\n")

if not mirror:
    exit()

# Загружаем страницу команды
print("2. Загружаем страницу команды...")
url = f"{mirror}/team/541"
session = requests.Session()
session.get(mirror, headers=HEADERS, timeout=10)
resp = session.get(url, headers=HEADERS, timeout=15)
html = resp.text
print(f"   Размер: {len(html)} символов\n")

# Сохраняем HTML для анализа
with open('liveball_debug.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("3. HTML сохранён в liveball_debug.html\n")

# Ищем упоминания команд
print("4. Ищем упоминания команд в HTML:")
teams_to_find = ['betis', 'valencia', 'barcelona', 'sevilla', 'athletic', 'atletico']
for team in teams_to_find:
    count = html.lower().count(team)
    print(f"   '{team}': {count} раз")

print("\n5. Первые 5 match ID и их контекст:")
for i, match in enumerate(re.finditer(r'/match/(\d+)', html)):
    if i >= 5:
        break
    match_id = match.group(1)
    start = max(0, match.start() - 100)
    end = min(len(html), match.end() + 100)
    context = html[start:end]
    # Убираем теги
    context_clean = re.sub(r'<[^>]+>', ' ', context)
    context_clean = re.sub(r'\s+', ' ', context_clean).strip()[:150]
    print(f"\n   ID={match_id}:")
    print(f"   {context_clean}...")

print("\n\n✅ Готово! Открой liveball_debug.html и поищи 'betis' вручную")
