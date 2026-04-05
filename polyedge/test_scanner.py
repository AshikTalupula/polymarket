import sys
sys.path.insert(0, 'polyedge')
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
import market_scanner

markets = market_scanner.scan()
print(f"\n=== Scanner found: {len(markets)} markets ===")
for m in markets:
    print(f"  [{m['category']}] {m['question'][:60]}")
    print(f"      vol={m['volume']:.0f}  liq={m['liquidity']:.0f}  yes={m['yes_price']:.3f}  {m['hours_left']:.0f}h left")
