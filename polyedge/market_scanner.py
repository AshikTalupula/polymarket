"""
PolyEdge AI — Market Scanner
Pulls active Polymarket markets from the Gamma API and filters to the best
candidates for AI analysis.
"""
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional
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

        # Volume / liquidity filters
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

        # Category / tag filter
        tags = [t.get("label", "") if isinstance(t, dict) else str(t)
                for t in (raw.get("tags") or [])]
        if config.TARGET_CATEGORIES and not any(
            tc.lower() in " ".join(tags).lower()
            for tc in config.TARGET_CATEGORIES
        ):
            return None  # Skip markets outside target categories

        # Parse YES price from outcomePrices
        outcome_prices_raw = raw.get("outcomePrices") or []
        if isinstance(outcome_prices_raw, str):
            import json
            outcome_prices_raw = json.loads(outcome_prices_raw)
        yes_price = 0.5
        if outcome_prices_raw and len(outcome_prices_raw) >= 1:
            try:
                yes_price = float(outcome_prices_raw[0])
            except (ValueError, TypeError):
                pass

        # clobTokenIds — YES token is index 0
        clob_token_ids = raw.get("clobTokenIds") or []
        if isinstance(clob_token_ids, str):
            import json
            clob_token_ids = json.loads(clob_token_ids)

        yes_token_id = clob_token_ids[0] if clob_token_ids else ""
        no_token_id  = clob_token_ids[1] if len(clob_token_ids) > 1 else ""

        # Determine category
        category = "Other"
        for tc in config.TARGET_CATEGORIES:
            if any(tc.lower() in tag.lower() for tag in tags):
                category = tc
                break

        return {
            "market_id":        raw.get("conditionId") or raw.get("id", ""),
            "question":         raw.get("question", ""),
            "description":      raw.get("description", "")[:500],
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
    Returns the top N markets sorted by volume.
    Updates module-level _latest_markets.
    """
    global _latest_markets
    logger.info("Market scanner: fetching markets…")

    params = {
        "active":     "true",
        "closed":     "false",
        "limit":      config.SCANNER_MARKET_LIMIT,
        "order":      "volume",
        "ascending":  "false",
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

        # Handle paginated response shape
        if isinstance(raw_markets, dict):
            raw_markets = raw_markets.get("data") or raw_markets.get("markets") or []

        parsed = []
        for raw in raw_markets:
            m = _parse_market(raw)
            if m:
                parsed.append(m)

        # Sort by volume descending, take top N
        parsed.sort(key=lambda x: x["volume"], reverse=True)
        _latest_markets = parsed[: config.SCANNER_TOP_N]

        logger.info(
            "Market scanner: %d/%d markets passed filters → top %d selected",
            len(parsed), len(raw_markets), len(_latest_markets)
        )
        return _latest_markets

    except requests.exceptions.RequestException as e:
        logger.error("Market scanner HTTP error: %s", e)
        return _latest_markets  # return stale data rather than crashing


def get_latest_markets() -> list[dict]:
    """Return the most recently scanned markets without triggering a new scan."""
    return _latest_markets


def get_market_by_id(market_id: str) -> Optional[dict]:
    """Lookup a single market from the in-memory cache."""
    for m in _latest_markets:
        if m["market_id"] == market_id:
            return m
    return None
