import requests
import json

LEON_API = "https://leon.ru/api-2/betline"
h = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://leon.ru",
    "Referer": "https://leon.ru/",
}

url = f"{LEON_API}/events/all?ctag=ru-RU&sport_id=1970324836974595&hideClosed=true&flags=reg,urlv2,mm2,rrc,nodup"
resp = requests.get(url, headers=h, timeout=15)
data = resp.json()
events = data.get("events", [])

# Find Real Madrid vs Benfica
for e in events:
    name = e.get("name", "")
    nd = e.get("nameDefault", "")
    combined = name + " " + nd
    if ("Реал Мадрид" in combined or "Real Madrid" in combined) and ("Бенфика" in combined or "Benfica" in combined):
        eid = e.get("id")
        print(f"=== MATCH: {name} | {nd} ===")
        print(f"ID: {eid}, betline: {e.get('betline')}")
        print()

        dr = requests.get(f"{LEON_API}/event/all?ctag=ru-RU&eventId={eid}&flags=reg,urlv2,mm2,rrc,nodup", headers=h, timeout=10)
        dd = dr.json()
        mkts = dd.get("markets", [])
        print(f"Total markets: {len(mkts)}")
        print()

        # ALL markets with пенал
        print("=== ALL MARKETS WITH 'пенал' ===")
        for m in mkts:
            mn = m.get("name", "")
            if "пенал" in mn.lower():
                op = m.get("open")
                runners = [(r.get("name"), r.get("price"), r.get("open")) for r in m.get("runners", [])]
                print(f"  NAME: [{mn}]  open={op}")
                for rn, rp, ro in runners:
                    flag = ""
                    if rp and (rp < 1.01 or rp > 50):
                        flag = " <<< UNREALISTIC"
                    print(f"    {rn}: {rp} (open={ro}){flag}")
                print()

        # ALL markets with карточ/желт
        print("=== ALL MARKETS WITH 'карточ' or 'желт' ===")
        for m in mkts:
            mn = m.get("name", "")
            ml = mn.lower()
            if "карточ" in ml or "желт" in ml:
                op = m.get("open")
                runners = [(r.get("name"), r.get("price"), r.get("open")) for r in m.get("runners", [])]
                print(f"  NAME: [{mn}]  open={op}")
                for rn, rp, ro in runners:
                    flag = ""
                    if rp and (rp < 1.01 or rp > 50):
                        flag = " <<< UNREALISTIC"
                    print(f"    {rn}: {rp} (open={ro}){flag}")
                print()

        break
else:
    print("Real Madrid vs Benfica match NOT FOUND on Leon")
    # Try any Real Madrid match
    for e in events:
        name = e.get("name", "")
        nd = e.get("nameDefault", "")
        if "Real Madrid" in nd or "Реал Мадрид" in name:
            print(f"  Available: {name} | {nd}")

print()
print("=" * 60)
print("=== NOW CHECKING API OUTPUT ===")
print("=" * 60)

try:
    api_resp = requests.get("http://localhost:8000/api/match/next", timeout=10)
    api_data = api_resp.json()
    match = api_data.get("match", {})
    print(f"\nMatch: {match.get('home_team')} vs {match.get('away_team')}")
    print(f"Date: {match.get('date')}")
    print()

    bet_markets = match.get("bet_markets", [])
    print(f"Total bet_markets: {len(bet_markets)}")
    print()

    for m in bet_markets:
        cat = m.get("category", "")
        mtype = m.get("type", "")
        bets = m.get("bets", [])
        print(f"--- {cat} ({mtype}) ---")
        for b in bets:
            odds = b.get("odds", 0)
            flag = ""
            if odds < 1.01:
                flag = " <<< TOO LOW"
            elif odds > 50:
                flag = " <<< TOO HIGH"
            print(f"  {b.get('name')}: {odds}{flag}")
        print()
except Exception as ex:
    print(f"API error: {ex}")
