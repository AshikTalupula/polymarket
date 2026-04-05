"""
PolyEdge AI — Signal Detector
Evaluates AI analysis results against market prices and generates
typed trade signals with full metadata.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import config
import database as db
from ai_analyst import AnalysisResult, ShockAnalysisResult

logger = logging.getLogger(__name__)


# ─── Signal Data Classes ──────────────────────────────────────────────────────

SIGNAL_TYPES = {
    "STRONG_BUY_YES",
    "BUY_YES",
    "STRONG_BUY_NO",
    "BUY_NO",
    "SHOCK_TRADE",
    "NO_TRADE",
}


@dataclass
class TradeSignal:
    signal_type:       str
    market_id:         str
    market_question:   str
    direction:         str       # BUY_YES | BUY_NO
    edge:              float     # % edge
    confidence:        str       # LOW / MEDIUM / HIGH
    ai_probability:    float     # 0-100
    market_price:      float     # 0-1 (YES price)
    category:          str
    yes_token_id:      str
    no_token_id:       str
    end_date:          str
    volume:            float
    liquidity:         float
    reasoning:         str
    is_strong:         bool = False
    timestamp:         datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        self.is_strong = self.signal_type in ("STRONG_BUY_YES", "STRONG_BUY_NO", "SHOCK_TRADE")


# ─── Signal Evaluation Logic ──────────────────────────────────────────────────

class SignalDetector:

    def evaluate(self,
                 market: dict,
                 analysis: AnalysisResult) -> Optional[TradeSignal]:
        """
        Compare AI probability vs market price and classify as a signal.
        All signals (including NO_TRADE) are logged to SQLite.
        Only actionable signals are returned.
        """
        edge       = analysis.edge
        confidence = analysis.confidence
        volume     = market.get("volume", 0)
        direction  = analysis.trade_direction

        signal_type = "NO_TRADE"

        if direction == "BUY_YES":
            if edge >= config.STRONG_BUY_EDGE_THRESHOLD and \
               confidence == "HIGH" and \
               volume >= config.STRONG_BUY_MIN_VOLUME:
                signal_type = "STRONG_BUY_YES"
            elif edge >= config.BUY_EDGE_THRESHOLD and \
                 confidence in ("MEDIUM", "HIGH"):
                signal_type = "BUY_YES"

        elif direction == "BUY_NO":
            # Negative edge means market is OVER-pricing YES → buy NO
            abs_edge = abs(edge)
            if abs_edge >= config.STRONG_BUY_EDGE_THRESHOLD and \
               confidence == "HIGH" and \
               volume >= config.STRONG_BUY_MIN_VOLUME:
                signal_type = "STRONG_BUY_NO"
            elif abs_edge >= config.BUY_EDGE_THRESHOLD and \
                 confidence in ("MEDIUM", "HIGH"):
                signal_type = "BUY_NO"

        acted_on = signal_type != "NO_TRADE"

        # Always log signal to SQLite
        db.log_signal(
            market_question=market["question"],
            market_id=market["market_id"],
            ai_probability=analysis.true_probability,
            market_price=market["yes_price"] * 100,
            edge=edge,
            confidence=confidence,
            direction=signal_type,
            acted_on=acted_on,
        )

        if signal_type == "NO_TRADE":
            logger.debug(
                "No trade signal: edge=%.1f%% conf=%s dir=%s market='%s'",
                edge, confidence, direction, market["question"][:40]
            )
            return None

        signal = TradeSignal(
            signal_type=market["question"],
            market_id=market["market_id"],
            market_question=market["question"],
            direction=direction,
            edge=edge,
            confidence=confidence,
            ai_probability=analysis.true_probability,
            market_price=market["yes_price"],
            category=market.get("category", "Other"),
            yes_token_id=market.get("yes_token_id", ""),
            no_token_id=market.get("no_token_id", ""),
            end_date=market.get("end_date", ""),
            volume=volume,
            liquidity=market.get("liquidity", 0),
            reasoning=analysis.reasoning,
        )
        # Fix: signal_type should be signal_type not market question
        signal.signal_type = signal_type

        logger.info(
            "🎯 Signal [%s] | Edge=%.1f%% | Conf=%s | '%s'",
            signal_type, edge, confidence, market["question"][:50]
        )
        return signal

    def evaluate_shock(self,
                       market: dict,
                       shock: ShockAnalysisResult,
                       previous_analysis: Optional[AnalysisResult] = None
                       ) -> Optional[TradeSignal]:
        """
        Evaluate a shock analysis result and generate a SHOCK_TRADE signal
        if urgency is IMMEDIATE and probability_shift > threshold.
        """
        if shock.urgency != "IMMEDIATE":
            return None
        if abs(shock.probability_shift) < config.SHOCK_MIN_PROBABILITY_SHIFT:
            return None

        # Determine direction from probability shift
        direction = "BUY_YES" if shock.probability_shift > 0 else "BUY_NO"
        edge = shock.probability_shift  # positive or negative

        db.log_signal(
            market_question=market["question"],
            market_id=market["market_id"],
            ai_probability=shock.new_probability,
            market_price=market["yes_price"] * 100,
            edge=edge,
            confidence="HIGH",
            direction="SHOCK_TRADE",
            acted_on=True,
        )

        signal = TradeSignal(
            signal_type="SHOCK_TRADE",
            market_id=market["market_id"],
            market_question=market["question"],
            direction=direction,
            edge=edge,
            confidence="HIGH",
            ai_probability=shock.new_probability,
            market_price=market["yes_price"],
            category=market.get("category", "Other"),
            yes_token_id=market.get("yes_token_id", ""),
            no_token_id=market.get("no_token_id", ""),
            end_date=market.get("end_date", ""),
            volume=market.get("volume", 0),
            liquidity=market.get("liquidity", 0),
            reasoning=shock.reasoning,
        )

        logger.warning(
            "⚡ SHOCK_TRADE signal generated: shift=%.1f%% urgency=%s market='%s'",
            shock.probability_shift, shock.urgency, market["question"][:50]
        )
        return signal
