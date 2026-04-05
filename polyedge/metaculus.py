"""
PolyEdge AI — Metaculus Integration
Fetches aggregated human superforecaster probabilities from Metaculus.
Free API, no authentication required.

Metaculus is one of the best-calibrated forecasting platforms.
Their community aggregate beats most individual AI models.
"""
import logging
import requests
from typing import Optional
from functools import lru_cache
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

METACULUS_BASE = "https://www.metaculus.com/api2"
HEADERS = {"User-Agent": "PolyEdgeAI/2.0 (trading research bot)"}


def _keyword_overlap(q1: str, q2: str) -> float:
    """Simple keyword overlap score between two questions."""
    stop = {"will","the","a","an","in","on","by","at","for","of","to","is","be",
            "are","was","were","this","that","with","and","or","not","from","who",
            "what","when","which","between","than","more","before","after"}
    w1 = {w.lower() for w in q1.split() if len(w) > 3 and w.lower() not in stop}
    w2 = {w.lower() for w in q2.split() if len(w) > 3 and w.lower() not in stop}
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / max(len(w1), len(w2))


@lru_cache(maxsize=64)
def _cached_search(query: str) -> list:
    """Cached Metaculus search — avoids hitting API too often."""
    try:
        resp = requests.get(
            f"{METACULUS_BASE}/questions/",
            params={
                "search":        query,
                "status":        "open",
                "resolve_time__gt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "type":          "forecast",
                "limit":         10,
            },
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        logger.debug("Metaculus search error for '%s': %s", query, e)
        return []


def get_metaculus_probability(market_question: str) -> Optional[dict]:
    """
    Search Metaculus for a question matching the market question.
    Returns a dict with probability and metadata, or None if no match found.

    Returns:
        {
            "probability": 0.22,           # 0-1 scale
            "community_prediction": 0.22,
            "num_predictions": 145,
            "title": "Will there be an Iran ceasefire...",
            "url": "https://www.metaculus.com/questions/...",
            "resolve_time": "2025-05-01T00:00:00Z",
        }
    """
    # Extract 3-4 key terms from the market question for searching
    stop = {"will","the","a","an","in","on","by","at","for","of","to","is","be",
            "are","was","this","that","between","more","before","after","than"}
    words = [w.strip("?,.") for w in market_question.split()
             if len(w.strip("?,.")) > 3 and w.lower() not in stop]
    if not words:
        return None

    query = " ".join(words[:4])
    results = _cached_search(query)

    best_match = None
    best_score = 0.35  # Minimum similarity threshold

    for r in results:
        meta_q = r.get("title", "")
        score  = _keyword_overlap(market_question, meta_q)
        if score > best_score:
            best_score = score
            best_match = r

    if not best_match:
        return None

    # Extract the community forecast probability
    community = best_match.get("community_prediction") or {}
    q2_mean   = community.get("q2")   # median (50th percentile)

    if q2_mean is None:
        # Try older API format
        q2_mean = (
            best_match.get("metaculus_prediction") or
            best_match.get("resolution_criteria_description")
        )
        if not isinstance(q2_mean, float):
            return None

    num_preds = best_match.get("number_of_forecasters", 0)
    if num_preds < 5:  # Not enough forecasters for reliable signal
        return None

    return {
        "probability":           round(float(q2_mean), 4),
        "community_prediction":  round(float(q2_mean), 4),
        "num_predictors":        num_preds,
        "title":                 best_match.get("title", ""),
        "url":                   f"https://www.metaculus.com/questions/{best_match.get('id','')}",
        "similarity_score":      round(best_score, 2),
        "resolve_time":          best_match.get("resolve_time", ""),
    }


def get_community_summary(meta: dict) -> str:
    """Format Metaculus result as a readable summary for AI prompts."""
    if not meta:
        return ""
    pct = round(meta["probability"] * 100, 1)
    return (
        f"Metaculus community forecast ({meta['num_predictors']} forecasters): "
        f"{pct}% probability. Source: {meta['url']}"
    )
