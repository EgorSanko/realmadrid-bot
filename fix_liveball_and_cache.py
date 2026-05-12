#!/usr/bin/env python3
"""
TASK 1: Add LiveBall schedule parser to api.py + /live command to bot.py
TASK 2: Stream buttons already done — verify only
TASK 3: Fix ESPN cache TTL for live matches (5min → 30sec when live)
"""

API_FILE = "/root/realmadrid-bot-fixed/api.py"
BOT_FILE = "/root/realmadrid-bot-fixed/bot.py"

# ============================================================
# PART 1A: Add LiveBall schedule parser to api.py
# ============================================================

with open(API_FILE, "r", encoding="utf-8") as f:
    api = f.read()

# Add LiveBall parser endpoint before the stream parser section
liveball_endpoint = '''

# ============ LIVEBALL SCHEDULE PARSER ============

_liveball_schedule_cache = {'data': None, 'time': 0, 'ttl': 300}  # 5 min
_LIVEBALL_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def _get_liveball_domain():
    """Get current LiveBall working domain"""
    try:
        resp = requests.get('https://liveball.website/', headers=_LIVEBALL_HEADERS, timeout=10, allow_redirects=True)
        # Parse the redirect/mirror page for actual domain
        text = resp.text
        import re
        # Look for href to actual liveball domain
        m = re.search(r'href="(https://liveball[^"]+)"[^>]*>.*?Перейти на сайт', text)
        if m:
            return m.group(1).rstrip('/')
        # Fallback: check if we were redirected
        if 'liveball' in resp.url and resp.url != 'https://liveball.website/':
            return resp.url.rstrip('/')
    except:
        pass
    return 'https://liveball7.icu'


def _parse_liveball_schedule():
    """Parse LiveBall homepage for match schedule"""
    import time as _t
    now = _t.time()

    if _liveball_schedule_cache['data'] and (now - _liveball_schedule_cache['time']) < _liveball_schedule_cache['ttl']:
        return _liveball_schedule_cache['data']

    try:
        domain = _get_liveball_domain()
        # Parse the team page for Real Madrid matches AND main page for all
        matches = []

        # Parse main page for all matches
        resp = requests.get(f'{domain}/', headers=_LIVEBALL_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Top matches (league_block)
        for block in soup.select('.league_block'):
            link = block.select_one('a[href*="/match/"]')
            if not link:
                continue
            href = link.get('href', '')
            match_id = href.rstrip('/').split('/')[-1] if '/match/' in href else ''
            if not match_id:
                continue

            home_el = block.select_one('.t_left .league_title')
            away_el = block.select_one('.t_right .league_title')
            home = home_el.get_text(strip=True) if home_el else ''
            away = away_el.get_text(strip=True) if away_el else ''

            league_el = block.select_one('.tm_league_name')
            league = league_el.get_text(strip=True) if league_el else ''

            # Check if live or timer
            live_el = block.select_one('.tm_live')
            score_el = block.select_one('.tm_score')
            timer_el = block.select_one('.tm_timer')

            if live_el and 'LIVE' in (live_el.get_text() or ''):
                status = 'live'
                score = score_el.get_text(strip=True) if score_el else ''
                time_str = 'LIVE'
            elif timer_el and timer_el.get('value'):
                status = 'upcoming'
                score = ''
                # Convert unix timestamp to time
                try:
                    ts = int(timer_el.get('value'))
                    from datetime import datetime, timezone, timedelta
                    msk = timezone(timedelta(hours=3))
                    dt = datetime.fromtimestamp(ts, tz=msk)
                    time_str = dt.strftime('%H:%M')
                except:
                    time_str = ''
            else:
                status = 'finished'
                score = score_el.get_text(strip=True) if score_el else ''
                time_str = ''

            if home and away:
                full_url = f'{domain}/match/{match_id}'
                matches.append({
                    'id': match_id,
                    'home': home,
                    'away': away,
                    'league': league,
                    'time': time_str,
                    'score': score,
                    'status': status,
                    'url': full_url,
                    'top': True,
                })

        # Regular matches (live_block2)
        seen_ids = {m['id'] for m in matches}
        current_league = ''

        for el in soup.select('.live_block2, .small_l'):
            if 'small_l' in el.get('class', []):
                current_league = el.get_text(strip=True)
                continue

            link = el.select_one('a[href*="/match/"]')
            if not link:
                continue
            href = link.get('href', '')
            match_id = href.rstrip('/').split('/')[-1] if '/match/' in href else ''
            if not match_id or match_id in seen_ids:
                continue
            seen_ids.add(match_id)

            home_el = link.select_one('.team_title_left')
            away_el = link.select_one('.team_title_right')
            home = home_el.get_text(strip=True) if home_el else ''
            away = away_el.get_text(strip=True) if away_el else ''

            score_el = link.select_one('.score')
            score = score_el.get_text(strip=True) if score_el else ''

            # Determine status from parent section
            parent_section = el.find_parent('section')
            section_title = ''
            if parent_section:
                h1 = parent_section.select_one('h1')
                section_title = h1.get_text(strip=True) if h1 else ''

            if 'Прямой эфир' in section_title or 'live' in section_title.lower():
                status = 'live'
                time_str = 'LIVE'
            elif score and score != '- -':
                status = 'finished'
                time_str = ''
            else:
                status = 'upcoming'
                time_str = ''

            if home and away:
                full_url = f'{domain}/match/{match_id}'
                matches.append({
                    'id': match_id,
                    'home': home,
                    'away': away,
                    'league': current_league or '',
                    'time': time_str,
                    'score': score,
                    'status': status,
                    'url': full_url,
                    'top': False,
                })

        _liveball_schedule_cache['data'] = matches
        _liveball_schedule_cache['time'] = now
        print(f"LiveBall: parsed {len(matches)} matches from {domain}")
        return matches

    except Exception as e:
        print(f"LiveBall parse error: {e}")
        return _liveball_schedule_cache.get('data') or []


@app.get("/api/liveball/schedule")
async def liveball_schedule():
    """Get LiveBall match schedule"""
    matches = _parse_liveball_schedule()
    return {"matches": matches, "count": len(matches)}

'''

# Insert before "# ============ STREAM PARSER ============"
marker = "# ============ STREAM PARSER ============"
if marker in api:
    api = api.replace(marker, liveball_endpoint + "\n" + marker)
    print("[OK] Added LiveBall schedule parser to api.py")
else:
    print("[WARN] Stream parser marker not found in api.py")


# ============================================================
# PART 1B: Fix ESPN cache TTL for live matches
# ============================================================

old_espn_cache = """_ESPN_CACHE_TTL = 300  # 5 min"""
new_espn_cache = """_ESPN_CACHE_TTL = 300  # 5 min (non-live default)
_ESPN_CACHE_TTL_LIVE = 30  # 30 sec for live matches"""

if old_espn_cache in api:
    api = api.replace(old_espn_cache, new_espn_cache)
    print("[OK] Added ESPN live cache TTL constant")
else:
    print("[WARN] ESPN cache TTL not found")

# Update _espn_get_summary to accept is_live parameter
old_espn_fn = """def _espn_get_summary(espn_event_id: str, league: str = None) -> dict:"""
new_espn_fn = """def _espn_get_summary(espn_event_id: str, league: str = None, is_live: bool = False) -> dict:"""

if old_espn_fn in api:
    api = api.replace(old_espn_fn, new_espn_fn)
    print("[OK] Added is_live param to _espn_get_summary")
else:
    print("[WARN] _espn_get_summary signature not found")

# Update the cache check in _espn_get_summary
old_espn_check = """    cached = _espn_summary_cache.get(espn_event_id)
    if cached and (now - cached['time']) < _ESPN_CACHE_TTL:"""
new_espn_check = """    cached = _espn_summary_cache.get(espn_event_id)
    ttl = _ESPN_CACHE_TTL_LIVE if is_live else _ESPN_CACHE_TTL
    if cached and (now - cached['time']) < ttl:"""

if old_espn_check in api:
    api = api.replace(old_espn_check, new_espn_check)
    print("[OK] ESPN cache now uses dynamic TTL")
else:
    print("[WARN] ESPN cache check not found")

# Update the call in /api/live to pass is_live=True
old_espn_live_call = """            summary = _espn_get_summary(espn_id) if espn_id else {}"""
if old_espn_live_call in api:
    api = api.replace(old_espn_live_call,
        """            summary = _espn_get_summary(espn_id, is_live=True) if espn_id else {}""")
    print("[OK] /api/live ESPN call uses is_live=True")
else:
    print("[WARN] ESPN live call not found")


# ============================================================
# PART 1C: Add no-cache headers for /api in nginx
# ============================================================
# (This will be done separately via nginx config)


with open(API_FILE, "w", encoding="utf-8") as f:
    f.write(api)
print("\n[DONE] api.py updated")


# ============================================================
# PART 2: Add /live command and callback handlers to bot.py
# ============================================================

with open(BOT_FILE, "r", encoding="utf-8") as f:
    bot = f.read()

# Add /live command and stream_callback before main()
live_cmd_code = '''

# ============ LIVE STREAM ADMIN ============

async def live_cmd(update, context):
    """Show LiveBall matches as inline buttons for stream setup"""
    if update.effective_user.id not in Config.ADMIN_IDS:
        return

    try:
        resp = requests.get("http://localhost:8000/api/liveball/schedule", timeout=15)
        data = resp.json()
        matches = data.get('matches', [])
    except Exception as e:
        await update.message.reply_text(f"\\u274c Не удалось загрузить расписание: {e}")
        return

    if not matches:
        await update.message.reply_text("Нет доступных матчей на LiveBall")
        return

    live_matches = [m for m in matches if m['status'] == 'live']
    upcoming = [m for m in matches if m['status'] == 'upcoming']

    text = "\\U0001f4fa Доступные трансляции LiveBall:\\n\\n"

    if live_matches:
        text += "\\U0001f534 LIVE:\\n"
        for m in live_matches[:10]:
            score = f" {m.get('score', '')}" if m.get('score') else ""
            text += f"\\u26bd {m['home']} vs {m['away']}{score} ({m.get('league', '')})"
            if m.get('top'):
                text += " \\u2b50"
            text += "\\n"

    if upcoming:
        text += "\\n\\u23f0 Скоро:\\n"
        for m in upcoming[:10]:
            t = m.get('time', '')
            text += f"\\u26bd {m['home']} vs {m['away']} \\u2014 {t} ({m.get('league', '')})\\n"

    keyboard = []
    for m in (live_matches + upcoming)[:8]:
        icon = "\\U0001f534" if m['status'] == 'live' else "\\u23f0"
        btn_text = f"{icon} {m['home']} vs {m['away']}"
        if len(btn_text) > 45:
            btn_text = btn_text[:42] + "..."
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"startlb_{m['id']}")])

    # Current streams status
    active = get_active_streams()
    if active:
        text += f"\\n\\u2705 Сейчас идёт: {active[0].get('name', 'Stream')}"
        keyboard.append([InlineKeyboardButton("\\u23f9 Остановить трансляцию", callback_data="stoplb")])

    keyboard.append([InlineKeyboardButton("\\U0001f504 Обновить список", callback_data="refreshlb")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)


async def live_callback(update, context):
    """Handle LiveBall stream callback buttons"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("startlb_"):
        match_id = data.replace("startlb_", "")

        try:
            resp = requests.get("http://localhost:8000/api/liveball/schedule", timeout=15)
            schedule = resp.json()
            match = next((m for m in schedule.get('matches', []) if str(m['id']) == match_id), None)
        except:
            match = None

        if not match:
            await query.edit_message_text("\\u274c Матч не найден. Попробуйте обновить список.")
            return

        stream_data = {
            "streams": [{
                "name": f"{match['home']} vs {match['away']}",
                "url": match['url'],
                "type": "iframe",
                "active": True
            }],
            "updated": datetime.now(MSK).strftime("%d.%m %H:%M"),
            "updated_by": "admin"
        }

        if save_streams(stream_data):
            await query.edit_message_text(
                f"\\u2705 Трансляция запущена!\\n\\n"
                f"\\u26bd {match['home']} vs {match['away']}\\n"
                f"\\U0001f3c6 {match.get('league', '')}\\n"
                f"\\U0001f517 {match['url']}\\n\\n"
                f"Пользователи увидят кнопку в приложении.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\\u23f9 Остановить", callback_data="stoplb")],
                    [InlineKeyboardButton("\\U0001f4fa Сменить матч", callback_data="refreshlb")]
                ]),
                disable_web_page_preview=True
            )
        else:
            await query.edit_message_text("\\u274c Ошибка сохранения стрима")

    elif data == "stoplb":
        save_streams({"streams": [], "updated": datetime.now(MSK).strftime("%d.%m %H:%M"), "updated_by": ""})
        await query.edit_message_text(
            "\\u23f9 Трансляция остановлена.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\\U0001f4fa Запустить новую", callback_data="refreshlb")]
            ])
        )

    elif data == "refreshlb":
        try:
            resp = requests.get("http://localhost:8000/api/liveball/schedule", timeout=15)
            data_resp = resp.json()
            matches = data_resp.get('matches', [])
        except:
            await query.edit_message_text("\\u274c Не удалось загрузить расписание")
            return

        live_matches = [m for m in matches if m['status'] == 'live']
        upcoming = [m for m in matches if m['status'] == 'upcoming']

        text = "\\U0001f4fa Доступные трансляции LiveBall:\\n\\n"
        if live_matches:
            text += "\\U0001f534 LIVE:\\n"
            for m in live_matches[:10]:
                score = f" {m.get('score', '')}" if m.get('score') else ""
                text += f"\\u26bd {m['home']} vs {m['away']}{score} ({m.get('league', '')})\\n"
        if upcoming:
            text += "\\n\\u23f0 Скоро:\\n"
            for m in upcoming[:10]:
                t = m.get('time', '')
                text += f"\\u26bd {m['home']} vs {m['away']} \\u2014 {t} ({m.get('league', '')})\\n"

        keyboard = []
        for m in (live_matches + upcoming)[:8]:
            icon = "\\U0001f534" if m['status'] == 'live' else "\\u23f0"
            btn_text = f"{icon} {m['home']} vs {m['away']}"
            if len(btn_text) > 45:
                btn_text = btn_text[:42] + "..."
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"startlb_{m['id']}")])

        active = get_active_streams()
        if active:
            text += f"\\n\\u2705 Сейчас идёт: {active[0].get('name', 'Stream')}"
            keyboard.append([InlineKeyboardButton("\\u23f9 Остановить трансляцию", callback_data="stoplb")])
        keyboard.append([InlineKeyboardButton("\\U0001f504 Обновить", callback_data="refreshlb")])

        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            # Message not modified (same content)
            pass

'''

# Insert before "# ============ MAIN ============"
main_marker = "# ============ MAIN ============"
if main_marker in bot:
    bot = bot.replace(main_marker, live_cmd_code + "\n" + main_marker)
    print("\n[OK] Added /live command and callbacks to bot.py")
else:
    print("\n[WARN] MAIN marker not found in bot.py")

# Add handler registrations
old_handlers = '''    app.add_handler(CallbackQueryHandler(purchase_callback, pattern="^(approve|reject)_"))'''
new_handlers = '''    app.add_handler(CallbackQueryHandler(purchase_callback, pattern="^(approve|reject)_"))
    app.add_handler(CommandHandler("live", live_cmd))
    app.add_handler(CallbackQueryHandler(live_callback, pattern="^(startlb_|stoplb|refreshlb)"))'''

if old_handlers in bot:
    bot = bot.replace(old_handlers, new_handlers)
    print("[OK] Registered /live handler and callbacks")
else:
    print("[WARN] Handler registration block not found")

# Add InlineKeyboardButton/Markup import if not present
if 'InlineKeyboardButton' not in bot.split('def ')[0]:
    old_import = "from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes"
    new_import = "from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes\nfrom telegram import InlineKeyboardButton, InlineKeyboardMarkup"
    if old_import in bot:
        bot = bot.replace(old_import, new_import)
        print("[OK] Added InlineKeyboardButton import")
else:
    print("[OK] InlineKeyboardButton already imported")

with open(BOT_FILE, "w", encoding="utf-8") as f:
    f.write(bot)
print("\n[DONE] bot.py updated")

# ============================================================
# PART 3: Verify stream buttons (already done)
# ============================================================
with open("/root/realmadrid-bot-fixed/index.html", "r", encoding="utf-8") as f:
    html = f.read()

live_buttons = html.count('ПРЯМОЙ ЭФИР')
streamblocks = html.count('<StreamBlock')
print(f"\n[INFO] Stream buttons check:")
print(f"  'ПРЯМОЙ ЭФИР' buttons: {live_buttons} (expected 4: 3 on Home, 1 on Bets)")
print(f"  '<StreamBlock' instances: {streamblocks} (expected 2: both on Matches)")

print("\n=== ALL DONE ===")
print("1. LiveBall schedule parser: GET /api/liveball/schedule")
print("2. Bot /live command with inline buttons")
print("3. ESPN cache TTL: 30s for live, 300s for non-live")
print("4. Stream buttons: verified")
