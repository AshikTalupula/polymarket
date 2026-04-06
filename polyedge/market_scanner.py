"""
PolyEdge AI — Market Scanner
Pulls active Polymarket markets from the Gamma API, applies soft scoring,
and filters to the best candidates for AI analysis.
"""
import logging
import requests
import math
from datetime import datetime, timezone
from typing import Optional
import json

import config

logger = logging.getLogger(__name__)

GAMMA_MARKETS_URL = f"{config.GAMMA_API_BASE}/markets"

_latest_markets: list[dict] = []

# Transparency counters
_reject_stats = {
    "filtered_inactive": 0,
    "filtered_expiry": 0,
    "filtered_low_volume": 0,
    "filtered_low_liquidity": 0,
    "filtered_extreme_price": 0,
    "parsed_success": 0,
    "total_fetched": 0
}

def _reset_stats():
    for k in _reject_stats:
        _reject_stats[k] = 0

def _parse_market(raw: dict) -> Optional[dict]:
    """
    Stage A (Hard Filters) & Stage B (Soft Scoring)
    """
    try:
        # ------- STAGE A: Hard Filters -------
        if not raw.get("active") or raw.get("closed"):
            _reject_stats["filtered_inactive"] += 1
            return None

        end_date_str = raw.get("endDate") or raw.get("end_date_iso")
        if not end_date_str:
            _reject_stats["filtered_expiry"] += 1
            return None
            
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        hours_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left < config.SCANNER_MIN_HOURS_TO_EXPIRY:
            _reject_stats["filtered_expiry"] += 1
            return None

        volume = float(raw.get("volume", 0) or 0)
        liquidity = float(raw.get("liquidity", 0) or 0)

        if volume < config.SCANNER_MIN_VOLUME:
            _reject_stats["filtered_low_volume"] += 1
            return None
        if liquidity < config.SCANNER_MIN_LIQUIDITY:
            _reject_stats["filtered_low_liquidity"] += 1
            return None

        # Price parsing
        outcome_prices_raw = raw.get("outcomePrices") or []
        if isinstance(outcome_prices_raw, str):
            try:
                outcome_prices_raw = json.loads(outcome_prices_raw)
            except Exception:
                outcome_prices_raw = []
        yes_price = 0.5
        if outcome_prices_raw and len(outcome_prices_raw) >= 1:
            try:
                yes_price = float(outcome_prices_raw[0])
            except (ValueError, TypeError):
                pass
                
        # IMPORTANT: Hard reject extreme dead zones
        if yes_price < 0.02 or yes_price > 0.98:
            _reject_stats["filtered_extreme_price"] += 1
            return None

        # Category parsing
        tags_raw = raw.get("tags") or []
        tags = [t.get("label", "") if isinstance(t, dict) else str(t) for t in tags_raw]
        tag_str  = " ".join(tags).lower()
        question = raw.get("question", "").lower()
        combined = tag_str + " " + question
        category = "Other"

        CATEGORY_KEYWORDS = {
            "Politics":  ["election","vote","president","congress","senate","trump","harris",
                          "democrat","republican","biden","political","minister","parliament",
                          "governor","policy","government","referendum","poll","campaign"],
            "Crypto":    ["bitcoin","btc","ethereum","eth","crypto","blockchain","defi",
                          "nft","solana","sol","usdc","token","altcoin","binance","coinbase",
                          "sec","ripple","xrp","polygon","matic","doge","dogecoin"],
            "Economics": ["inflation","fed","interest rate","gdp","recession","jobs","cpi",
                          "employment","economy","fiscal","treasury","tariff","trade",
                          "market","stock","nasdaq","s&p","dow","oil","gas","energy"],
            "Finance":   ["earnings","ipo","merger","acquisition","revenue","profit","bank",
                          "loan","debt","bond","yield","hedge fund","etf","fund"],
            "Sports":    ["nba","nfl","mlb","nhl","soccer","football","basketball","tennis",
                          "golf","championship","world cup","super bowl","playoffs"],
        }
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                category = cat
                break

        clob_token_ids = raw.get("clobTokenIds") or []
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except Exception:
                clob_token_ids = []

        yes_token_id = clob_token_ids[0] if clob_token_ids else ""
        no_token_id  = clob_token_ids[1] if len(clob_token_ids) > 1 else ""

        # ------- STAGE B: Soft Scoring -------
        
        score_vol = math.log10(max(1.0, volume))
        score_liq = math.log10(max(1.0, liquidity))
        
        # Soft penalty for extreme prices approaching 0 or 1
        # E.g. quadratic difference from 0.5: max penalty at 0 or 1 is 0.5 (scaled)
        price_diff = abs(yes_price - 0.5)
        price_penalty = 2.0 * (price_diff ** 2)

        # Logarithmic decay for time (prefer 1 week over 6 months)
        time_penalty = math.log10(max(10.0, hours_left)) * 0.5
        
        score = (score_vol * 1.0) + (score_liq * 1.5) - price_penalty - time_penalty

        _reject_stats["parsed_success"] += 1

        return {
            "market_id":        raw.get("conditionId") or raw.get("id", ""),
            "question":         raw.get("question", ""),
            "description":      (raw.get("description") or "")[:500],
            "yes_price":        yes_price,
            "volume":           volume,
            "liquidity":        liquidity,
            "end_date":         end_date_str,
            "hours_left":       round(hours_left, 1),
            "category":         category,
            "tags":             tags,
            "yes_token_id":     yes_token_id,
            "no_token_id":      no_token_id,
            "condition_id":     raw.get("conditionId", ""),
            "score":            round(score, 3)
        }
    except Exception as e:
        logger.debug("Market parse error: %s | raw keys: %s", e, list(raw.keys()))
        return None


def scan() -> list[dict]:
    """
    Fetch and filter Polymarket markets.
    Uses pagination, deduplicates, and sorts by a composite tradability score.
    """
    global _latest_markets
    _reset_stats()
    logger.info("Market scanner (Discovery Mode): fetching markets…")

    parsed = []
    seen_ids = set()

    limit_per_req = 100
    target_total = config.SCANNER_MARKET_LIMIT

    fetch_configs = [
        {"order": "liquidity"},
        {"order": "volume24hr"},
    ]

    for fc in fetch_configs:
        offset = 0
        while offset < target_total:
            params = {
                "active":    "true",
                "closed":    "false",
                "limit":     limit_per_req,
                "offset":    offset,
                "order":     fc["order"],
                "ascending": "false",
            }
            try:
                resp = requests.get(
                    GAMMA_MARKETS_URL,
                    params=params,
                    timeout=15,
                    headers={"User-Agent": "PolyEdgeAI/1.0"}
                )
                resp.raise_for_status()
                raw_markets = resp.json()

                if isinstance(raw_markets, dict):
                    raw_markets = raw_markets.get("data") or raw_markets.get("markets") or []
                
                if not raw_markets:
                    break

                _reject_stats["total_fetched"] += len(raw_markets)

                for raw in raw_markets:
                    mid = raw.get("conditionId") or raw.get("id", "")
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    m = _parse_market(raw)
                    if m:
                        parsed.append(m)

                offset += limit_per_req

            except requests.exceptions.RequestException as e:
                logger.error("Market scanner HTTP error (%s offset %d): %s", fc["order"], offset, e)
                break

    # Log transparency info
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(" SCAN SUMMARY (Discovery Engine)")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(" Total Fetched:          %d", _reject_stats["total_fetched"])
    logger.info(" Parsed (Valid):         %d", _reject_stats["parsed_success"])
    logger.info(" Rejected - Expiry:      %d", _reject_stats["filtered_expiry"])
    logger.info(" Rejected - Inactive:    %d", _reject_stats["filtered_inactive"])
    logger.info(" Rejected - Low Liq:     %d", _reject_stats["filtered_low_liquidity"])
    logger.info(" Rejected - Low Vol:     %d", _reject_stats["filtered_low_volume"])
    logger.info(" Rejected - Dead Price:  %d", _reject_stats["filtered_extreme_price"])
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Sort by SCORE descending
    parsed.sort(key=lambda x: x["score"], reverse=True)

    # Apply soft category cap
    final_markets = []
    category_counts = {}
    max_per_category = max(1, int(config.SCANNER_TOP_N * config.SCANNER_MAX_CATEGORY_SHARE))

    for m in parsed:
        cat = m["category"]
        count = category_counts.get(cat, 0)
        
        # Soft cap enforcement
        if count >= max_per_category and len(final_markets) < config.SCANNER_TOP_N:
            continue
            
        final_markets.append(m)
        category_counts[cat] = count + 1
        
        if len(final_markets) >= config.SCANNER_TOP_N:
            break

    # Backfill if soft cap starved the final list
    if len(final_markets) < config.SCANNER_TOP_N:
        for m in parsed:
            if m not in final_markets:
                final_markets.append(m)
                if len(final_markets) >= config.SCANNER_TOP_N:
                    break

    _latest_markets = final_markets

    logger.info("🔥 Top %d Markets Selected:", len(_latest_markets))
    if _latest_markets:
        for m in _latest_markets:
            logger.info("  [%s] %.2f Score | Vol: %dk | Liq: %dk | P: %.2f | %s",
                        m["category"].ljust(9),
                        m["score"],
                        int(m["volume"]//1000),
                        int(m["liquidity"]//1000),
                        m["yes_price"],
                        m["question"][:65])
    else:
        logger.warning("Scanner returned 0 markets.")

    return _latest_markets

def get_latest_markets() -> list[dict]:
    return _latest_markets

def get_market_by_id(market_id: str) -> Optional[dict]:
    for m in _latest_markets:
        if m["market_id"] == market_id:
            return m
    return None
