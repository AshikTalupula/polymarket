"""
PolyEdge AI — Market Scanner
Pulls active Polymarket markets from the Gamma API and filters to the best
candidates for AI analysis.
"""
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional
import json
import config

logger = logging.getLogger(__name__)

GAMMA_MARKETS_URL = f"{config.GAMMA_API_BASE}/markets"

# Shared in-memory state so other modules can read the latest scan
_latest_markets: list[dict] = []


def _parse_market(raw: dict) -> Optional[dict]:
    """
    Parse a single raw market dict from Gamma API into our normalised format.
    Returns None if the market fails any filter criteria.
    """
    try:
        # Skip inactive / closed
        if not raw.get("active") or raw.get("closed"):
            return None

        # Volume / liquidity filters (relaxed from originals)
        volume    = float(raw.get("volume", 0) or 0)
        liquidity = float(raw.get("liquidity", 0) or 0)
        if volume < config.SCANNER_MIN_VOLUME:
            return None
        if liquidity < config.SCANNER_MIN_LIQUIDITY:
            return None

        # Expiry filter — must have >= 48 hours left
        end_date_str = raw.get("endDate") or raw.get("end_date_iso")
        if not end_date_str:
            return None
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        hours_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left < config.SCANNER_MIN_HOURS_TO_EXPIRY:
            return None

        # ── Category filter (LENIENT) ─────────────────────────────────────────
        # Gamma API often returns empty tags[], so we do keyword matching on
        # the question text itself as a fallback.
        tags_raw = raw.get("tags") or []
        tags = [t.get("label", "") if isinstance(t, dict) else str(t)
                for t in tags_raw]
        tag_str  = " ".join(tags).lower()
        question = raw.get("question", "").lower()

        # Combine tags + question for category matching
        combined = tag_str + " " + question
        category = "Other"
        matched  = False

        if config.TARGET_CATEGORIES:
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
                    matched  = True
                    break

            # If user defined explicit TARGET_CATEGORIES and nothing matched, skip
            # BUT only skip if there are proper tags — if tags are empty, be lenient
            if not matched and tags:
                return None
            # If tags are empty AND no keyword match → still include as "Other"
            # to avoid scanner returning 0 markets
        
        # Parse YES price from outcomePrices
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

        # clobTokenIds — YES token is index 0
        clob_token_ids = raw.get("clobTokenIds") or []
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except Exception:
                clob_token_ids = []

        yes_token_id = clob_token_ids[0] if clob_token_ids else ""
        no_token_id  = clob_token_ids[1] if len(clob_token_ids) > 1 else ""

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
        }
    except Exception as e:
        logger.debug("Market parse error: %s | raw keys: %s", e, list(raw.keys()))
        return None


def scan() -> list[dict]:
    """
    Fetch and filter Polymarket markets.
    Fetches a large page sorted by liquidity (more reliable than volume)
    so high-quality markets are captured.
    Returns the top N markets sorted by volume.
    """
    global _latest_markets
    logger.info("Market scanner: fetching markets…")

    parsed = []

    # Fetch multiple sort orders to maximise coverage
    fetch_configs = [
        {"order": "liquidity",  "limit": 100},
        {"order": "volume24hr", "limit": 100},
    ]

    seen_ids = set()
    for fc in fetch_configs:
        params = {
            "active":    "true",
            "closed":    "false",
            "limit":     fc["limit"],
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

            logger.info("Raw markets from Gamma (%s sort): %d", fc["order"], len(raw_markets))

            for raw in raw_markets:
                mid = raw.get("conditionId") or raw.get("id", "")
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                m = _parse_market(raw)
                if m:
                    parsed.append(m)

        except requests.exceptions.RequestException as e:
            logger.error("Market scanner HTTP error (%s): %s", fc["order"], e)

    # Sort by volume descending, take top N
    parsed.sort(key=lambda x: x["volume"], reverse=True)
    _latest_markets = parsed[: config.SCANNER_TOP_N]

    logger.info(
        "Market scanner: %d markets passed filters → top %d selected",
        len(parsed), len(_latest_markets)
    )
    if _latest_markets:
        for m in _latest_markets[:3]:
            logger.info("  • [%s] %s (vol=%.0f liq=%.0f)",
                        m["category"], m["question"][:55], m["volume"], m["liquidity"])
    else:
        logger.warning("Market scanner: 0 markets passed filters! Check SCANNER_MIN_VOLUME / SCANNER_MIN_LIQUIDITY / SCANNER_MIN_HOURS_TO_EXPIRY in config.py")

    return _latest_markets


def get_latest_markets() -> list[dict]:
    return _latest_markets


def get_market_by_id(market_id: str) -> Optional[dict]:
    for m in _latest_markets:
        if m["market_id"] == market_id:
            return m
    return None
