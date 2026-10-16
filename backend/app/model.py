"""Единая форма данных, не зависящая от источника, и общие помощники нормализаторов.

Все нормализаторы (fotmob/sofascore/espn/livescore) отдают одинаковые структуры:
match / fixture / table / team. Чего источник не умеет — None или пустой список,
а список `available` честно перечисляет, что в ответе есть.
"""
import re
import unicodedata
from datetime import datetime, timezone

# ---------- картинки: только наши пути (nginx proxy_cache) ----------


def img_team(fid) -> str | None:
    return f"/img/team/{int(fid)}.png" if _is_id(fid) else None


def img_player(fid) -> str | None:
    return f"/img/player/{int(fid)}.png" if _is_id(fid) else None


def img_league(fid) -> str | None:
    return f"/img/league/{int(fid)}.png" if _is_id(fid) else None


def img_flag(code) -> str | None:
    iso = iso2(code)
    return f"/img/flag/{iso}.svg" if iso else None


def _is_id(v) -> bool:
    try:
        return int(v) > 0
    except (TypeError, ValueError):
        return False


# FotMob даёт коды стран в стиле FIFA (POR, GER, NED, SUI), иногда ISO alpha-3.
# Здесь оба варианта → ISO alpha-2 (как во flagcdn), плюс домашние нации Британии.
_A3 = {
    "AFG": "af", "ALB": "al", "ALG": "dz", "DZA": "dz", "AND": "ad", "ANG": "ao", "AGO": "ao",
    "ARG": "ar", "ARM": "am", "AUS": "au", "AUT": "at", "AZE": "az", "BAH": "bs", "BHS": "bs",
    "BHR": "bh", "BRN": "bh", "BAN": "bd", "BGD": "bd", "BLR": "by", "BEL": "be", "BEN": "bj",
    "BOL": "bo", "BIH": "ba", "BOT": "bw", "BWA": "bw", "BRA": "br", "BUL": "bg", "BGR": "bg",
    "BFA": "bf", "BDI": "bi", "CMR": "cm", "CAN": "ca", "CPV": "cv", "CTA": "cf", "CAF": "cf",
    "CHA": "td", "TCD": "td", "CHI": "cl", "CHL": "cl", "CHN": "cn", "COL": "co", "COM": "km",
    "CGO": "cg", "COG": "cg", "COD": "cd", "CRC": "cr", "CRI": "cr", "CIV": "ci", "CRO": "hr",
    "HRV": "hr", "CUB": "cu", "CUW": "cw", "CYP": "cy", "CZE": "cz", "DEN": "dk", "DNK": "dk",
    "DJI": "dj", "DOM": "do", "ECU": "ec", "EGY": "eg", "SLV": "sv", "ESA": "sv", "EQG": "gq",
    "GNQ": "gq", "ERI": "er", "EST": "ee", "ETH": "et", "FRO": "fo", "FIJ": "fj", "FJI": "fj",
    "FIN": "fi", "FRA": "fr", "GAB": "ga", "GAM": "gm", "GMB": "gm", "GEO": "ge", "GER": "de",
    "DEU": "de", "GHA": "gh", "GIB": "gi", "GRE": "gr", "GRC": "gr", "GRN": "gd", "GUA": "gt",
    "GTM": "gt", "GUI": "gn", "GIN": "gn", "GNB": "gw", "GUY": "gy", "HAI": "ht", "HTI": "ht",
    "HON": "hn", "HND": "hn", "HKG": "hk", "HUN": "hu", "ISL": "is", "IND": "in", "IDN": "id",
    "INA": "id", "IRN": "ir", "IRQ": "iq", "IRL": "ie", "ISR": "il", "ITA": "it", "JAM": "jm",
    "JPN": "jp", "JOR": "jo", "KAZ": "kz", "KEN": "ke", "KOR": "kr", "PRK": "kp", "KVX": "xk",
    "KOS": "xk", "XKX": "xk", "KUW": "kw", "KWT": "kw", "KGZ": "kg", "LAO": "la", "LVA": "lv",
    "LAT": "lv", "LBN": "lb", "LIB": "lb", "LES": "ls", "LSO": "ls", "LBR": "lr", "LBY": "ly",
    "LIE": "li", "LTU": "lt", "LUX": "lu", "MAC": "mo", "MKD": "mk", "MAD": "mg", "MDG": "mg",
    "MWI": "mw", "MAS": "my", "MYS": "my", "MDV": "mv", "MLI": "ml", "MLT": "mt", "MTN": "mr",
    "MRT": "mr", "MRI": "mu", "MUS": "mu", "MEX": "mx", "MDA": "md", "MON": "mc", "MCO": "mc",
    "MNG": "mn", "MNE": "me", "MAR": "ma", "MOZ": "mz", "MYA": "mm", "MMR": "mm", "NAM": "na",
    "NEP": "np", "NPL": "np", "NED": "nl", "NLD": "nl", "NCL": "nc", "NZL": "nz", "NCA": "ni",
    "NIC": "ni", "NIG": "ne", "NER": "ne", "NGA": "ng", "NOR": "no", "OMA": "om", "OMN": "om",
    "PAK": "pk", "PLE": "ps", "PSE": "ps", "PAN": "pa", "PNG": "pg", "PAR": "py", "PRY": "py",
    "PER": "pe", "PHI": "ph", "PHL": "ph", "POL": "pl", "POR": "pt", "PRT": "pt", "PUR": "pr",
    "PRI": "pr", "QAT": "qa", "ROU": "ro", "RUS": "ru", "RWA": "rw", "KSA": "sa", "SAU": "sa",
    "SEN": "sn", "SRB": "rs", "SLE": "sl", "SGP": "sg", "SIN": "sg", "SVK": "sk", "SVN": "si",
    "SOL": "sb", "SLB": "sb", "SOM": "so", "RSA": "za", "ZAF": "za", "SSD": "ss", "ESP": "es",
    "SRI": "lk", "LKA": "lk", "SDN": "sd", "SUD": "sd", "SUR": "sr", "SWE": "se", "SUI": "ch",
    "CHE": "ch", "SYR": "sy", "TAH": "pf", "TPE": "tw", "TWN": "tw", "TJK": "tj", "TAN": "tz",
    "TZA": "tz", "THA": "th", "TOG": "tg", "TGO": "tg", "TRI": "tt", "TTO": "tt", "TUN": "tn",
    "TUR": "tr", "TKM": "tm", "UGA": "ug", "UKR": "ua", "UAE": "ae", "ARE": "ae", "USA": "us",
    "URU": "uy", "URY": "uy", "UZB": "uz", "VEN": "ve", "VIE": "vn", "VNM": "vn", "WAL": "gb-wls",
    "YEM": "ye", "ZAM": "zm", "ZMB": "zm", "ZIM": "zw", "ZWE": "zw", "ENG": "gb-eng",
    "SCO": "gb-sct", "NIR": "gb-nir", "GBR": "gb", "MSR": "ms", "BER": "bm", "BMU": "bm",
    "ARU": "aw", "ABW": "aw", "GLP": "gp", "MTQ": "mq", "GUF": "gf", "REU": "re", "MYT": "yt",
    "SKN": "kn", "KNA": "kn", "LCA": "lc", "VIN": "vc", "VCT": "vc", "BRB": "bb", "BAR": "bb",
    "BLZ": "bz", "ATG": "ag", "DMA": "dm", "CAY": "ky", "CYM": "ky", "TCA": "tc", "VGB": "vg",
    "VIR": "vi", "ASA": "as", "GUM": "gu", "SAM": "ws", "WSM": "ws", "TGA": "to", "TON": "to",
    "VAN": "vu", "VUT": "vu", "SEY": "sc", "SYC": "sc", "STP": "st", "SWZ": "sz", "ESW": "sz",
    "BHU": "bt", "BTN": "bt", "BRU": "bn", "CAM": "kh", "KHM": "kh", "TLS": "tl", "SMR": "sm",
    "VAT": "va", "IOM": "im", "IMN": "im", "JEY": "je", "GGY": "gg",
}


def iso2(code) -> str | None:
    if not code or not isinstance(code, str):
        return None
    c = code.strip()
    if len(c) == 2 and c.isalpha():
        return c.lower()
    if c.lower() in ("gb-eng", "gb-sct", "gb-wls", "gb-nir"):
        return c.lower()
    return _A3.get(c.upper())


# ---------- время и статусы ----------


def iso_utc(v) -> str | None:
    """Unix-время / ISO-строка → '2026-10-14T19:00:00Z'."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        dt = datetime.fromtimestamp(float(v), timezone.utc)
    else:
        s = str(v).strip().replace("Z", "+00:00")
        if re.fullmatch(r"\d{14}", s):  # LiveScore: 20261014190000
            dt = datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        else:
            if re.fullmatch(r".*T\d\d:\d\d\+00:00", s):  # ESPN: 2026-10-14T19:00Z
                s = s.replace("+00:00", ":00+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(iso: str | None) -> float | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


STATES = ("scheduled", "live", "halftime", "finished", "postponed", "cancelled", "abandoned")


def status(state: str, minute: int | None = None, added: int | None = None, label: str | None = None) -> dict:
    assert state in STATES, state
    live = state in ("live", "halftime")
    return {
        "state": state,
        "live": live,
        "finished": state == "finished",
        "minute": minute if live else None,
        "added": added if live else None,
        "label": label,  # как отдал источник (FT, HT, 67', Pen…) — для отладки
    }


def result_for(team_id, home_id, hs, as_) -> str | None:
    """W/D/L с точки зрения team_id."""
    if hs is None or as_ is None:
        return None
    if hs == as_:
        return "D"
    we_home = str(team_id) == str(home_id)
    return "W" if (hs > as_) == we_home else "L"


# ---------- имена ----------


def name_key(s: str | None) -> str:
    """Ключ для сравнения имён между источниками: без диакритики, регистра и знаков."""
    if not s:
        return ""
    s = s.replace("ß", "ss").replace("ø", "o").replace("Ø", "O").replace("ł", "l").replace("đ", "d")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("ue", "u").replace("oe", "o").replace("ae", "a")  # Rüdiger / Ruediger
    return re.sub(r"[^a-z]", "", s)


def same_person(a: str | None, b: str | None) -> bool:
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return False
    if ka == kb or ka in kb or kb in ka:
        return True
    la, lb = name_key((a or "").split()[-1]), name_key((b or "").split()[-1])
    return len(la) > 3 and la == lb


_CLUB_NOISE = re.compile(r"\b(fc|cf|ac|as|ss|sc|ssc|cd|ud|rcd|rc|sd|ca|club|de|calcio|football)\b")


def team_key(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = _CLUB_NOISE.sub(" ", s)
    return re.sub(r"[^a-z]", "", s)


def same_team(a: str | None, b: str | None) -> bool:
    ka, kb = team_key(a), team_key(b)
    if not ka or not kb:
        return False
    if ka == kb or ka in kb or kb in ka:
        return True
    # «Atletico Madrid» / «Atlético de Madrid», «Internazionale» / «Inter»
    return ka[:5] == kb[:5]


# ---------- числа ----------


def num(v):
    """'469 (86%)' → 469, '54%' → 54, '1.41' → 1.41, '112.8 km' → 112.8."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    if not m:
        return None
    x = float(m.group(1))
    return int(x) if x.is_integer() and "." not in m.group(1) else x


# ---------- статистика: общий каталог ключей ----------

# (ключ, группа). Подписи по-русски делает фронт.
STAT_CATALOG = [
    ("possession", "top"), ("xg", "top"), ("shots_total", "top"), ("shots_on_target", "top"),
    ("big_chances", "top"), ("corners", "top"),
    ("shots_off_target", "shots"), ("shots_blocked", "shots"), ("shots_woodwork", "shots"),
    ("shots_inside_box", "shots"), ("shots_outside_box", "shots"), ("xg_on_target", "shots"),
    ("passes_total", "passes"), ("passes_accurate", "passes"), ("long_balls_accurate", "passes"),
    ("crosses_accurate", "passes"), ("touches_opp_box", "passes"),
    ("tackles", "defence"), ("interceptions", "defence"), ("clearances", "defence"), ("saves", "defence"),
    ("fouls", "discipline"), ("offsides", "discipline"), ("yellow_cards", "discipline"),
    ("red_cards", "discipline"),
]
_STAT_ORDER = {k: i for i, (k, _) in enumerate(STAT_CATALOG)}
_STAT_GROUP = dict(STAT_CATALOG)


def stat_list(pairs: dict) -> list:
    """{key: (home, away)} → упорядоченный список по каталогу; чужие ключи отбрасываются."""
    out = []
    for k, (h, a) in pairs.items():
        if k not in _STAT_ORDER or (h is None and a is None):
            continue
        out.append({"key": k, "group": _STAT_GROUP[k], "home": num(h), "away": num(a)})
    out.sort(key=lambda x: _STAT_ORDER[x["key"]])
    return out


# ---------- матч ----------

AVAILABLE_KEYS = (
    "events", "assists", "lineups", "lineup_positions", "ratings", "stats", "stats_periods",
    "xg", "shotmap", "shot_xg", "momentum", "potm", "highlights", "h2h", "form", "venue", "referee",
    "player_photos",
)


def empty_match() -> dict:
    side = {"id": None, "name": None, "short": None, "score": None, "ht_score": None, "logo": None}
    return {
        "id": None,
        "ids": {"fotmob": None, "sofascore": None, "espn": None, "livescore": None},
        "kickoff": None,
        "status": status("scheduled"),
        "tournament": {"id": None, "name": None, "round": None, "logo": None},
        "venue": None,      # {"name", "city"}
        "referee": None,
        "attendance": None,
        "home": dict(side),
        "away": dict(side),
        "events": [],
        "lineups": None,    # {"home": {...}, "away": {...}, "confirmed": bool}
        "stats": None,      # {"all": [...], "first_half": [...], "second_half": [...]}
        "shots": [],
        "momentum": [],
        "potm": None,
        "highlights": None,
        "h2h": None,
        "form": None,       # {"home": ["W",...], "away": [...]}
    }


def event(kind: str, minute, added=None, side=None, **kw) -> dict:
    e = {"type": kind, "minute": minute, "added": added or None, "side": side}
    e.update(kw)
    return e


def person(pid=None, name=None, fotmob_id=None) -> dict | None:
    if not name and not pid:
        return None
    return {"id": fotmob_id, "name": name, "photo": img_player(fotmob_id)}


def lineup_player(name, number=None, fotmob_id=None, position=None, rating=None,
                  x=None, y=None, captain=False, sub_in=None, sub_out=None, source_id=None) -> dict:
    return {
        "id": fotmob_id, "source_id": source_id, "name": name,
        "number": int(number) if str(number or "").isdigit() else None,
        "position": position, "rating": round(float(rating), 1) if rating not in (None, "") else None,
        "x": x, "y": y, "captain": bool(captain),
        "sub_in": sub_in, "sub_out": sub_out, "photo": img_player(fotmob_id),
    }


# координаты линий как у FotMob verticalLayout: x 0..1 поперёк поля, y 0..1 от своих ворот
_LINE_X = {1: [0.5], 2: [0.3, 0.7], 3: [0.21, 0.5, 0.79], 4: [0.12, 0.38, 0.62, 0.88],
           5: [0.1, 0.3, 0.5, 0.7, 0.9], 6: [0.08, 0.25, 0.42, 0.58, 0.75, 0.92]}


def formation_layout(formation: str | None, count: int = 11) -> list[tuple[float, float]] | None:
    """'4-2-3-1' → [(x, y)] для вратаря и линий в порядке, в каком их перечисляет источник."""
    try:
        lines = [int(x) for x in str(formation).replace(" ", "").split("-") if x]
    except ValueError:
        return None
    if not lines or sum(lines) + 1 != count or max(lines) > 6:
        return None
    n = len(lines)
    ys = [0.29 + i * (0.58 / (n - 1)) for i in range(n)] if n > 1 else [0.5]
    out = [(0.5, 0.1)]
    for k, y in zip(lines, ys):
        out += [(x, round(y, 2)) for x in _LINE_X[k]]
    return out


def resolve_player(ctx: dict | None, side: str | None = None, number=None, name: str | None = None):
    """Чужой id игрока → id FotMob (для фото): сначала по (сторона, номер), потом по имени.

    ctx собирает сборщик из прошлых снимков FotMob: {"numbers": {"home": {"10": id}}, "names": {key: id},
    "last": {key: id}}. Без ctx — None (фото не будет, фронт спрячет).
    """
    if not ctx:
        return None
    if side and number not in (None, ""):
        v = (ctx.get("numbers") or {}).get(side, {}).get(str(number))
        if v:
            return v
    if name:
        v = (ctx.get("names") or {}).get(name_key(name))
        if v:
            return v
        return (ctx.get("last") or {}).get(name_key(name.split()[-1]))
    return None


def ctx_team(ctx: dict | None, source_team_id):
    return ((ctx or {}).get("teams") or {}).get(str(source_team_id))


def compute_available(m: dict) -> list[str]:
    a = []
    ev = m.get("events") or []
    if ev:
        a.append("events")
    if any(e.get("assist") for e in ev if e.get("type") == "goal"):
        a.append("assists")
    lu = m.get("lineups")
    if lu and (lu.get("home") or {}).get("starters"):
        a.append("lineups")
        starters = lu["home"]["starters"] + (lu.get("away") or {}).get("starters", [])
        if all(p.get("x") is not None for p in starters):
            a.append("lineup_positions")
        if any(p.get("rating") is not None for p in starters):
            a.append("ratings")
        if any(p.get("photo") for p in starters):
            a.append("player_photos")
    st = m.get("stats") or {}
    if st.get("all"):
        a.append("stats")
        if any(x["key"] == "xg" for x in st["all"]):
            a.append("xg")
    if st.get("first_half") or st.get("second_half"):
        a.append("stats_periods")
    if m.get("shots"):
        a.append("shotmap")
        if any(s.get("xg") is not None for s in m["shots"]):
            a.append("shot_xg")
    if m.get("momentum"):
        a.append("momentum")
    for k in ("potm", "highlights", "h2h", "form", "venue", "referee"):
        if m.get(k):
            a.append(k)
    return a


def finish_match(m: dict, source: str) -> dict:
    """Общая постобработка: сортировка событий, available, source."""
    # перерыв/конец тайма — после компенсированного времени своей минуты
    m["events"].sort(key=lambda e: ((e.get("minute") or 0),
                                    99 if e.get("type") == "period" else (e.get("added") or 0)))
    m["source"] = source
    m["available"] = compute_available(m)
    return m
