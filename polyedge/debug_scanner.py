import requests, json

resp = requests.get(
    'https://gamma-api.polymarket.com/markets',
    params={'active':'true','closed':'false','limit':10,'order':'volume','ascending':'false'},
    timeout=15
)
markets = resp.json()
if isinstance(markets, dict):
    markets = markets.get('data') or markets.get('markets') or []

print(f"Total returned: {len(markets)}")
for i, m in enumerate(markets[:5]):
    vol  = float(m.get('volume', 0) or 0)
    liq  = float(m.get('liquidity', 0) or 0)
    tags_raw = m.get('tags') or []
    tags = [t.get('label','') if isinstance(t,dict) else str(t) for t in tags_raw]
    end  = m.get('endDate') or m.get('end_date_iso','')
    q    = m.get('question','')
    print(f"\n[{i}] {q[:55]}")
    print(f"    vol={vol:.0f}  liq={liq:.0f}")
    print(f"    tags={tags}")
    print(f"    endDate={end[:25]}")
