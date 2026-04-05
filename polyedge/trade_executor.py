"""
PolyEdge AI — Trade Executor
Places and manages orders via py-clob-client.
Supports DRY_RUN mode for paper trading.
"""
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import config
import database as db
import risk_manager as rm
from signal_detector import TradeSignal

logger = logging.getLogger(__name__)

# ─── Optional CLOB client import ─────────────────────────────────────────────
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        OrderArgs,
        OrderType,
        PartialCreateOrderOptions,
    )
    from py_clob_client.constants import BUY, SELL
    _CLOB_AVAILABLE = True
except ImportError:
    _CLOB_AVAILABLE = False
    logger.warning("py-clob-client not installed — trading will be simulated.")


class TradeExecutor:
    def __init__(self):
        self._client: Optional[object] = None
        self._order_book: list[dict] = []   # in-memory open order tracking
        self._init_client()

    # ─── Client Init ─────────────────────────────────────────────────────

    def _init_client(self):
        if config.DRY_RUN:
            logger.info("DRY_RUN=True — CLOB client not initialised.")
            return
        if not _CLOB_AVAILABLE:
            logger.error("py-clob-client missing and DRY_RUN=False — cannot trade!")
            return
        if not config.POLYMARKET_PRIVATE_KEY:
            logger.error("POLYMARKET_PRIVATE_KEY not set.")
            return

        try:
            self._client = ClobClient(
                host=config.CLOB_API_BASE,
                key=config.POLYMARKET_PRIVATE_KEY,
                chain_id=config.POLYGON_CHAIN_ID,
                signature_type=config.SIGNATURE_TYPE,
                funder=config.POLYMARKET_FUNDER_ADDRESS or None,
            )

            # Use saved creds if available, otherwise derive
            if (config.POLYMARKET_API_KEY and
                    config.POLYMARKET_API_SECRET and
                    config.POLYMARKET_API_PASSPHRASE):
                from py_clob_client.clob_types import ApiCreds
                creds = ApiCreds(
                    api_key=config.POLYMARKET_API_KEY,
                    api_secret=config.POLYMARKET_API_SECRET,
                    api_passphrase=config.POLYMARKET_API_PASSPHRASE,
                )
                self._client.set_api_creds(creds)
            else:
                logger.info("Deriving API credentials from private key…")
                creds = self._client.create_or_derive_api_creds()
                self._client.set_api_creds(creds)

            logger.info("CLOB client initialised successfully.")
        except Exception as e:
            logger.error("CLOB client init error: %s", e)
            self._client = None

    # ─── Order Placement ─────────────────────────────────────────────────

    def _get_current_price(self, token_id: str) -> Optional[float]:
        """Fetch mid-price from CLOB orderbook for a token."""
        if not self._client:
            return None
        try:
            book = self._client.get_order_book(token_id)
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            if bids and asks:
                best_bid = float(bids[0]["price"])
                best_ask = float(asks[0]["price"])
                return round((best_bid + best_ask) / 2, 4)
        except Exception as e:
            logger.debug("Failed to fetch order book for %s: %s", token_id[:12], e)
        return None

    def place_limit_order(self,
                          token_id: str,
                          price: float,
                          size_usdc: float,
                          side: str,         # "BUY" or "SELL"
                          market_id: str,
                          market_question: str,
                          category: str,
                          direction: str     # BUY_YES | BUY_NO (for DB)
                          ) -> Optional[str]:
        """
        Place a limit order on Polymarket CLOB.
        Returns the order_id string or None on failure.

        In DRY_RUN mode, simulates the order and returns a fake order_id.
        """
        size_usdc = round(size_usdc, 2)
        if size_usdc < 1.0:
            logger.warning("Order too small ($%.2f) — skipping.", size_usdc)
            return None

        # ── DRY RUN ────────────────────────────────────────────────────
        if config.DRY_RUN or not self._client:
            fake_id = f"DRY-{int(time.time())}-{token_id[:8]}"
            logger.info(
                "[DRY_RUN] Simulated %s order: token=%s price=%.4f size=$%.2f",
                side, token_id[:12], price, size_usdc
            )
            trade_id = db.log_trade(
                market_id=market_id,
                market_question=market_question,
                direction=direction,
                entry_price=price,
                size_usdc=size_usdc,
                order_id=fake_id,
                token_id=token_id,
                category=category,
            )
            self._order_book.append({
                "order_id":   fake_id,
                "token_id":   token_id,
                "market_id":  market_id,
                "placed_at":  datetime.now(timezone.utc).isoformat(),
                "price":      price,
                "size_usdc":  size_usdc,
                "direction":  direction,
                "trade_id":   trade_id,
            })
            rm.update_capital(_current_after_buy(size_usdc))
            return fake_id

        # ── LIVE ORDER ─────────────────────────────────────────────────
        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size_usdc,
                side=BUY if side == "BUY" else SELL,
            )
            options = PartialCreateOrderOptions(tick_size=0.01)
            resp = self._client.create_and_post_order(order_args, options)

            order_id = resp.get("orderID") or resp.get("id", "unknown")
            logger.info(
                "✅ LIVE order placed: %s | token=%s | price=%.4f | size=$%.2f | id=%s",
                side, token_id[:12], price, size_usdc, order_id
            )

            trade_id = db.log_trade(
                market_id=market_id,
                market_question=market_question,
                direction=direction,
                entry_price=price,
                size_usdc=size_usdc,
                order_id=order_id,
                token_id=token_id,
                category=category,
            )
            self._order_book.append({
                "order_id":   order_id,
                "token_id":   token_id,
                "market_id":  market_id,
                "placed_at":  datetime.now(timezone.utc).isoformat(),
                "price":      price,
                "size_usdc":  size_usdc,
                "direction":  direction,
                "trade_id":   trade_id,
            })
            rm.update_capital(_current_after_buy(size_usdc))
            return order_id

        except Exception as e:
            logger.error("Order placement failed: %s", e)
            return None

    # ─── Execute Signal ───────────────────────────────────────────────────

    def execute_signal(self, signal: TradeSignal) -> Optional[str]:
        """
        Main entry point — applies risk checks and places an order for a signal.
        """
        # Edge validation (after fee)
        edge_ok, edge_msg = rm.RiskManager.validate_edge(abs(signal.edge))
        if not edge_ok:
            logger.info("Signal rejected — %s", edge_msg)
            return None

        # Portfolio risk check
        market_dict = {
            "market_id":  signal.market_id,
            "liquidity":  signal.liquidity,
            "hours_left": _hours_left(signal.end_date),
            "category":   signal.category,
        }
        can, reason = rm.RiskManager.can_trade(market_dict, signal.direction)
        if not can:
            logger.info("Signal blocked by risk manager: %s", reason)
            return None

        # Kelly position sizing
        capital = rm.get_current_capital()
        size = rm.RiskManager.calculate_position_size(
            edge_pct=abs(signal.edge),
            true_probability=signal.ai_probability,
            capital=capital,
        )
        if size < 1.0:
            logger.info("Position size too small ($%.2f) — skipping.", size)
            return None

        # Determine token and limit price
        if signal.direction == "BUY_YES":
            token_id    = signal.yes_token_id
            limit_price = round(
                signal.ai_probability / 100 - config.ORDER_LIMIT_OFFSET_PCT, 4
            )
            limit_price = max(0.01, min(0.99, limit_price))
        else:  # BUY_NO
            token_id    = signal.no_token_id
            no_true_prob = 1.0 - signal.ai_probability / 100
            limit_price  = round(no_true_prob - config.ORDER_LIMIT_OFFSET_PCT, 4)
            limit_price  = max(0.01, min(0.99, limit_price))

        if not token_id:
            logger.error("No token_id for direction=%s — cannot place order.",
                         signal.direction)
            return None

        logger.info(
            "Executing signal [%s]: market='%s' size=$%.2f price=%.4f",
            signal.signal_type, signal.market_question[:40], size, limit_price
        )

        return self.place_limit_order(
            token_id=token_id,
            price=limit_price,
            size_usdc=size,
            side="BUY",
            market_id=signal.market_id,
            market_question=signal.market_question,
            category=signal.category,
            direction=signal.direction,
        )

    # ─── Cancel Stale Orders ─────────────────────────────────────────────

    def cancel_stale_orders(self):
        """Cancel unfilled orders older than STALE_ORDER_MINUTES."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=config.STALE_ORDER_MINUTES
        )
        stale = [
            o for o in self._order_book
            if datetime.fromisoformat(o["placed_at"]) < cutoff
        ]
        for order in stale:
            oid = order["order_id"]
            if config.DRY_RUN or not self._client:
                logger.info("[DRY_RUN] Would cancel stale order: %s", oid)
            else:
                try:
                    self._client.cancel(oid)
                    logger.info("Cancelled stale order: %s", oid)
                except Exception as e:
                    logger.error("Failed to cancel order %s: %s", oid, e)
            # Remove from local book regardless
            self._order_book = [o for o in self._order_book if o["order_id"] != oid]

    # ─── Check & Exit Positions ───────────────────────────────────────────

    def check_and_exit_positions(self):
        """
        Runs every 5 minutes. Fetches current market prices, applies
        stop-loss and take-profit rules, and closes positions as needed.
        """
        open_positions = db.get_open_trades()
        if not open_positions:
            return

        # Build current price map
        current_prices: dict[str, float] = {}
        for pos in open_positions:
            market_id = pos["market_id"]
            if market_id in current_prices:
                continue

            # Try to get live price; fall back to synthetic for dry run
            token_id = pos.get("token_id", "")
            if token_id and self._client:
                price = self._get_current_price(token_id)
                if price is not None:
                    current_prices[market_id] = price
            if market_id not in current_prices:
                # Use entry price as fallback (no change simulated)
                current_prices[market_id] = pos.get("entry_price", 0.5)

        to_exit = rm.RiskManager.check_exit_conditions(open_positions, current_prices)

        for pos in to_exit:
            exit_price = pos.get("current_price", current_prices.get(pos["market_id"], 0))
            self._close_position(pos, exit_price)

    def _close_position(self, pos: dict, exit_price: float):
        """Sell/close a position and record the PnL."""
        trade_id    = pos["id"]
        market_id   = pos["market_id"]
        direction   = pos.get("direction", "BUY_YES")
        entry_price = pos.get("entry_price", exit_price)
        size_usdc   = pos.get("size_usdc", 0)
        token_id    = pos.get("token_id", "")
        exit_reason = pos.get("exit_reason", "MANUAL")

        pnl = rm.RiskManager.calculate_pnl(entry_price, exit_price, size_usdc, direction)

        if config.DRY_RUN or not self._client:
            logger.info(
                "[DRY_RUN] Close position id=%d exit_price=%.4f pnl=$%.4f reason=%s",
                trade_id, exit_price, pnl, exit_reason
            )
        else:
            try:
                # Place a SELL limit order at current price
                sell_args = OrderArgs(
                    token_id=token_id,
                    price=exit_price,
                    size=size_usdc,
                    side=SELL,
                )
                self._client.create_and_post_order(sell_args,
                                                   PartialCreateOrderOptions(tick_size=0.01))
                logger.info(
                    "✅ Position closed: market=%s exit=%.4f pnl=$%.4f reason=%s",
                    market_id[:12], exit_price, pnl, exit_reason
                )
            except Exception as e:
                logger.error("Failed to close position %d: %s", trade_id, e)
                return

        db.update_trade_exit(trade_id, exit_price, pnl, status="CLOSED")
        rm.update_capital(rm.get_current_capital() + pnl)
        self._order_book = [
            o for o in self._order_book if o.get("market_id") != market_id
        ]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _current_after_buy(size: float) -> float:
    """Capital after placing an order (subtract cost incl fee)."""
    fee = size * config.POLYMARKET_FEE_PCT / 100
    return round(rm.get_current_capital() - size - fee, 4)


def _hours_left(end_date_str: str) -> float:
    try:
        from datetime import datetime, timezone
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        return (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
    except Exception:
        return 999.0
