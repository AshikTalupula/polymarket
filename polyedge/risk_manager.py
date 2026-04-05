"""
PolyEdge AI — Risk Manager
Protects the $100 starting capital using Kelly Criterion sizing,
per-position stop-loss/take-profit, and portfolio-level exposure limits.
"""
import logging
from typing import Optional
import config
import database as db

logger = logging.getLogger(__name__)

# ─── Shared mutable capital state ────────────────────────────────────────────
# In production this should be synced with the CLOB balance query.
_current_capital = config.CAPITAL_TOTAL


def get_current_capital() -> float:
    return _current_capital


def update_capital(new_value: float):
    global _current_capital
    _current_capital = new_value
    logger.info("Capital updated: $%.4f", new_value)


class RiskManager:

    # ─── Position Sizing ─────────────────────────────────────────────────

    @staticmethod
    def calculate_position_size(edge_pct: float,
                                true_probability: float,
                                capital: Optional[float] = None) -> float:
        """
        Half-Kelly position sizing.

        Kelly fraction: f = edge / (1 - p_win)
        We use 0.5 * f for safety.

        Args:
            edge_pct: edge in percentage points (e.g. 12.0 for 12%)
            true_probability: AI estimate 0-100
            capital: current portfolio capital (defaults to current state)
        Returns:
            Dollar amount to bet (capped at MAX_SINGLE_TRADE)
        """
        if capital is None:
            capital = _current_capital

        max_bet = capital * config.MAX_SINGLE_TRADE_PCT

        if true_probability >= 100 or true_probability <= 0:
            return 0.0

        prob_win = true_probability / 100.0
        edge     = edge_pct / 100.0

        denominator = 1.0 - prob_win
        if denominator <= 0:
            return 0.0

        kelly_fraction = edge / denominator
        half_kelly      = kelly_fraction * config.KELLY_FRACTION
        half_kelly      = max(0.0, min(half_kelly, 1.0))  # clamp 0-1

        dollar_bet = round(capital * half_kelly, 4)
        return min(dollar_bet, max_bet)

    # ─── Can-Trade Gate ──────────────────────────────────────────────────

    @staticmethod
    def can_trade(market: dict, direction: str) -> tuple[bool, str]:
        """
        Full pre-trade checklist. Returns (can_trade, reason).
        """
        capital = _current_capital

        # 1. Minimum edge after fees
        # Caller is expected to furnish the `edge` value; we trust signal passed in.

        # 2. Daily loss limit
        daily_pnl = db.get_daily_pnl()
        if daily_pnl <= config.DAILY_LOSS_LIMIT:
            return False, f"Daily loss limit hit (PnL ${daily_pnl:.2f})"

        # 3. Max open positions
        open_trades = db.get_open_trades()
        if len(open_trades) >= config.MAX_OPEN_POSITIONS:
            return False, f"Max open positions reached ({config.MAX_OPEN_POSITIONS})"

        # 4. Category exposure limit
        category = market.get("category", "Other")
        cat_exposure = db.count_open_trades_by_category(category)
        max_cat_exposure = capital * config.MAX_EXPOSURE_PER_CATEGORY
        if cat_exposure >= max_cat_exposure:
            return False, (
                f"Category '{category}' exposure ${cat_exposure:.2f} "
                f">= limit ${max_cat_exposure:.2f}"
            )

        # 5. Minimum liquidity
        if market.get("liquidity", 0) < config.MIN_MARKET_LIQUIDITY:
            return False, (
                f"Market liquidity ${market['liquidity']:.0f} "
                f"< minimum ${config.MIN_MARKET_LIQUIDITY}"
            )

        # 6. Minimum time to resolution
        if market.get("hours_left", 0) < config.MIN_TIME_TO_RESOLUTION_HRS:
            return False, (
                f"Only {market['hours_left']:.1f}h to resolution "
                f"(min {config.MIN_TIME_TO_RESOLUTION_HRS}h)"
            )

        return True, "OK"

    # ─── Edge Validation ─────────────────────────────────────────────────

    @staticmethod
    def validate_edge(edge_pct: float) -> tuple[bool, str]:
        """Check edge is sufficient after the Polymarket 2% fee."""
        net_edge = edge_pct - config.POLYMARKET_FEE_PCT
        if net_edge < config.MIN_EDGE_AFTER_FEE:
            return False, (
                f"Net edge {net_edge:.1f}% < minimum {config.MIN_EDGE_AFTER_FEE}%"
            )
        return True, f"Net edge {net_edge:.1f}% passes"

    # ─── Exit Conditions ─────────────────────────────────────────────────

    @staticmethod
    def check_exit_conditions(open_positions: list[dict],
                              current_prices: dict[str, float]
                              ) -> list[dict]:
        """
        Evaluate each open position against stop-loss and take-profit rules.

        Args:
            open_positions: list of trade row dicts from DB
            current_prices: {market_id: current_yes_price (0-1)}
        Returns:
            List of positions that should be closed, with 'exit_reason' added.
        """
        to_exit = []
        for pos in open_positions:
            market_id    = pos["market_id"]
            entry_price  = pos.get("entry_price", 0)
            direction    = pos.get("direction", "BUY_YES")
            current_price = current_prices.get(market_id)

            if current_price is None or entry_price <= 0:
                continue

            # For BUY_NO, the token we hold is the NO token (price = 1 - yes_price)
            if direction == "BUY_NO":
                held_price = 1.0 - current_price
                held_entry = 1.0 - entry_price
            else:
                held_price = current_price
                held_entry = entry_price

            if held_entry <= 0:
                continue

            # Stop-loss: position value dropped 50% from entry
            if held_price <= held_entry * (1.0 - config.STOP_LOSS_PCT):
                pos = dict(pos)
                pos["exit_reason"] = "STOP_LOSS"
                pos["current_price"] = current_price
                to_exit.append(pos)
                logger.warning(
                    "🛑 STOP_LOSS triggered: market=%s entry=%.3f current=%.3f",
                    market_id[:12], held_entry, held_price
                )
                continue

            # Take-profit: YES probability >= 85% AND we entered below 60%
            if (direction == "BUY_YES" and
                    current_price * 100 >= config.TAKE_PROFIT_PROBABILITY and
                    entry_price * 100 < config.TAKE_PROFIT_ENTRY_CEILING):
                pos = dict(pos)
                pos["exit_reason"] = "TAKE_PROFIT"
                pos["current_price"] = current_price
                to_exit.append(pos)
                logger.info(
                    "✅ TAKE_PROFIT triggered: market=%s current_price=%.2f%%",
                    market_id[:12], current_price * 100
                )

        return to_exit

    @staticmethod
    def calculate_pnl(entry_price: float, exit_price: float,
                      size_usdc: float, direction: str) -> float:
        """
        Calculate net PnL including Polymarket's 2% fee on both legs.
        """
        fee_rate = config.POLYMARKET_FEE_PCT / 100.0
        if direction == "BUY_YES":
            tokens_bought = size_usdc / entry_price
            gross_exit    = tokens_bought * exit_price
        else:  # BUY_NO
            no_entry  = 1.0 - entry_price
            no_exit   = 1.0 - exit_price
            tokens_bought = size_usdc / no_entry if no_entry > 0 else 0
            gross_exit    = tokens_bought * no_exit

        fee_paid = size_usdc * fee_rate + gross_exit * fee_rate
        pnl = gross_exit - size_usdc - fee_paid
        return round(pnl, 6)
