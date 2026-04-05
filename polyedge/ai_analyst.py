"""
PolyEdge AI — AI Analyst
Groq-powered probability analysis engine using llama-3.3-70b-versatile.
"""
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from groq import Groq
from cachetools import TTLCache

import config

logger = logging.getLogger(__name__)

# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    market_id:       str
    true_probability: float    # 0-100
    confidence:      str       # LOW / MEDIUM / HIGH
    edge:            float     # true_prob - market_price (in %)
    reasoning:       str
    trade_direction: str       # BUY_YES / BUY_NO / NO_TRADE
    timestamp:       datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


@dataclass
class ShockAnalysisResult:
    market_id:         str
    new_probability:   float
    probability_shift: float
    urgency:           str    # IMMEDIATE / WAIT / IGNORE
    reasoning:         str
    timestamp:         datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


# ─── Prompts ──────────────────────────────────────────────────────────────────

STANDARD_PROMPT_TEMPLATE = """\
You are a professional prediction market analyst. Analyze this market with extreme precision.

MARKET: {question}
DESCRIPTION: {description}
CURRENT MARKET PRICE (YES probability): {price}%
RESOLUTION DATE: {end_date}
RECENT NEWS CONTEXT:
{news_headlines}

Analyze from THREE perspectives:

[SKEPTIC]: What hard evidence suggests YES is OVERPRICED? List specific reasons.
[BULL]: What evidence suggests YES is UNDERPRICED? List specific reasons.
[BASE RATE EXPERT]: Based on historical base rates for this type of event, what is the statistically correct probability?

Then synthesize:
- TRUE_PROBABILITY: Your best estimate as a single number (0-100)
- CONFIDENCE: LOW / MEDIUM / HIGH
- EDGE: TRUE_PROBABILITY minus current market price (positive = market underpricing YES)
- REASONING: One sentence summary
- TRADE_DIRECTION: BUY_YES / BUY_NO / NO_TRADE

Respond ONLY in this exact JSON format:
{{"true_probability": 67, "confidence": "HIGH", "edge": 12, "reasoning": "...", "trade_direction": "BUY_YES"}}
"""

SHOCK_PROMPT_TEMPLATE = """\
BREAKING NEWS DETECTED. Rapid reassessment required.

MARKET: {question}
PREVIOUS AI PROBABILITY: {previous_estimate}%
CURRENT MARKET PRICE: {price}%

BREAKING HEADLINES (last 10 minutes):
{shock_headlines}

How does this news CHANGE the probability? Respond ONLY in JSON:
{{"new_probability": 78, "probability_shift": 15, "urgency": "IMMEDIATE", "reasoning": "..."}}

urgency must be one of: IMMEDIATE, WAIT, IGNORE
"""


# ─── PolyAnalyst ──────────────────────────────────────────────────────────────

class PolyAnalyst:
    def __init__(self):
        self._client  = Groq(api_key=config.GROQ_API_KEY)
        # TTL cache: key = market_id, value = AnalysisResult
        self._cache: TTLCache = TTLCache(
            maxsize=50, ttl=config.AI_CACHE_TTL_SECONDS
        )

    # ── Internal helpers ────────────────────────────────────────────────────

    def _call_groq(self, prompt: str, retries: int = 3) -> str:
        """Call Groq API with exponential backoff on rate limit errors."""
        for attempt in range(retries):
            try:
                response = self._client.chat.completions.create(
                    model=config.GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=config.GROQ_MAX_TOKENS,
                    temperature=config.GROQ_TEMPERATURE,
                    response_format={"type": "json_object"},
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                err_str = str(e).lower()
                if "rate" in err_str or "429" in err_str:
                    wait = 2 ** attempt * 5   # 5s, 10s, 20s
                    logger.warning(
                        "Groq rate limit hit (attempt %d/%d), waiting %ds…",
                        attempt + 1, retries, wait
                    )
                    time.sleep(wait)
                else:
                    logger.error("Groq API error (attempt %d): %s", attempt + 1, e)
                    if attempt == retries - 1:
                        raise
                    time.sleep(2)
        raise RuntimeError("Groq API call failed after max retries")

    def _parse_json(self, raw: str) -> dict:
        """Parse JSON response, extracting from markdown code blocks if needed."""
        # Strip markdown fences
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:]
                try:
                    return json.loads(part.strip())
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Last resort: find first '{...}' block
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
            raise

    # ── Public Analysis Methods ─────────────────────────────────────────────

    def analyze(self, market: dict, news_context=None) -> Optional[AnalysisResult]:
        """
        Run standard probability analysis for a market.
        Results are cached per market_id for AI_CACHE_TTL_SECONDS.
        """
        market_id = market["market_id"]

        # Cache hit
        if market_id in self._cache:
            logger.debug("AI cache hit for market %s", market_id[:12])
            return self._cache[market_id]

        if not config.GROQ_API_KEY:
            logger.error("GROQ_API_KEY not configured — skipping AI analysis.")
            return None

        yes_price_pct = round(market["yes_price"] * 100, 2)
        headlines_text = (
            news_context.get_headlines_text()
            if news_context
            else "No news available."
        )

        prompt = STANDARD_PROMPT_TEMPLATE.format(
            question=market["question"],
            description=market.get("description", "N/A"),
            price=yes_price_pct,
            end_date=market.get("end_date", "Unknown"),
            news_headlines=headlines_text,
        )

        try:
            raw = self._call_groq(prompt)
            data = self._parse_json(raw)

            true_prob  = float(data.get("true_probability", 50))
            confidence = str(data.get("confidence", "LOW")).upper()
            edge       = float(data.get("edge", true_prob - yes_price_pct))
            reasoning  = str(data.get("reasoning", ""))
            direction  = str(data.get("trade_direction", "NO_TRADE")).upper()

            # Validate direction
            if direction not in ("BUY_YES", "BUY_NO", "NO_TRADE"):
                direction = "NO_TRADE"

            result = AnalysisResult(
                market_id=market_id,
                true_probability=true_prob,
                confidence=confidence,
                edge=edge,
                reasoning=reasoning,
                trade_direction=direction,
            )

            self._cache[market_id] = result
            logger.info(
                "AI: [%s] true_prob=%.1f%% edge=%.1f%% confidence=%s → %s",
                market["question"][:50], true_prob, edge, confidence, direction
            )
            return result

        except Exception as e:
            logger.error("AI analysis failed for '%s': %s",
                         market.get("question", "?")[:50], e)
            return None

    def analyze_shock(self, market: dict, news_context,
                      previous_estimate: float) -> Optional[ShockAnalysisResult]:
        """
        Rapid reassessment when a BREAKING_NEWS_SHOCK is detected.
        """
        if not config.GROQ_API_KEY:
            return None

        market_id    = market["market_id"]
        yes_price_pct = round(market["yes_price"] * 100, 2)

        prompt = SHOCK_PROMPT_TEMPLATE.format(
            question=market["question"],
            previous_estimate=round(previous_estimate, 1),
            price=yes_price_pct,
            shock_headlines=news_context.get_shock_text(),
        )

        try:
            raw  = self._call_groq(prompt)
            data = self._parse_json(raw)

            new_prob = float(data.get("new_probability", previous_estimate))
            shift    = float(data.get("probability_shift", new_prob - previous_estimate))
            urgency  = str(data.get("urgency", "IGNORE")).upper()
            reason   = str(data.get("reasoning", ""))

            if urgency not in ("IMMEDIATE", "WAIT", "IGNORE"):
                urgency = "IGNORE"

            result = ShockAnalysisResult(
                market_id=market_id,
                new_probability=new_prob,
                probability_shift=shift,
                urgency=urgency,
                reasoning=reason,
            )

            # Invalidate standard cache so next normal analysis is fresh
            self._cache.pop(market_id, None)

            logger.warning(
                "⚡ Shock analysis: [%s] shift=%.1f%% urgency=%s",
                market["question"][:50], shift, urgency
            )
            return result

        except Exception as e:
            logger.error("Shock analysis failed: %s", e)
            return None

    def invalidate_cache(self, market_id: str):
        self._cache.pop(market_id, None)
