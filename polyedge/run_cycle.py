"""
PolyEdge AI — Single Scan Cycle
Run ONE full scan+analyse+trade cycle.
Designed for GitHub Actions (called every 10 min).
Also callable directly for manual testing.
"""
import sys
import os
import logging
import time

# Ensure polyedge/ is on path whether called from root or polyedge/
_this_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _this_dir)

import config
import database as db
from news_engine     import NewsAggregator
from ai_analyst      import PolyAnalyst
from signal_detector import SignalDetector
from trade_executor  import TradeExecutor
import market_scanner

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("run_cycle")


def run_one_cycle() -> dict:
    """
    Execute one full scan cycle.
    Returns a summary dict for logging / GitHub Actions output.
    """
    t0 = time.time()
    summary = {
        "markets_scanned": 0,
        "signals_found":   0,
        "trades_executed": 0,
        "errors":          [],
    }

    logger.info("=" * 55)
    logger.info("  PolyEdge AI — Starting Scan Cycle")
    logger.info("  Mode: %s", "DRY RUN" if config.DRY_RUN else "LIVE")
    logger.info("=" * 55)

    # Validate critical config
    warnings = config.validate_config()
    for w in warnings:
        logger.warning("CONFIG: %s", w)

    # Initialise DB
    db.init_db()

    # Build singletons
    news   = NewsAggregator()
    ai     = PolyAnalyst()
    sig    = SignalDetector()
    trader = TradeExecutor()

    # ── 1. Refresh all news sources ────────────────────────────────
    logger.info("Step 1/4: Refreshing news sources…")
    try:
        news.refresh_all_sources()
    except Exception as e:
        logger.error("News refresh failed: %s", e)
        summary["errors"].append(f"news: {e}")

    # ── 2. Scan markets ────────────────────────────────────────────
    logger.info("Step 2/4: Scanning Polymarket…")
    try:
        markets = market_scanner.scan()
        summary["markets_scanned"] = len(markets)
        logger.info("Found %d markets", len(markets))
    except Exception as e:
        logger.error("Market scan failed: %s", e)
        summary["errors"].append(f"scan: {e}")
        markets = []

    # ── 3. Analyse + Signal + Trade ───────────────────────────────
    logger.info("Step 3/4: Analysing markets + generating signals…")
    for market in markets:
        try:
            ctx      = news.get_news_for_market(market)
            analysis = ai.analyze(market, ctx)
            if not analysis:
                continue

            # Shock path
            if ctx.is_shock:
                shock = ai.analyze_shock(market, ctx, analysis.true_probability)
                if shock:
                    signal = sig.evaluate_shock(market, shock, analysis)
                    if signal:
                        summary["signals_found"] += 1
                        if config.DRY_RUN or signal.is_strong:
                            trader.execute_signal(signal)
                            summary["trades_executed"] += 1
                continue

            # Standard path
            signal = sig.evaluate(market, analysis)
            if signal:
                summary["signals_found"] += 1
                if config.DRY_RUN or signal.is_strong:
                    trader.execute_signal(signal)
                    summary["trades_executed"] += 1

        except Exception as e:
            err_msg = f"{market.get('question','?')[:30]}: {e}"
            logger.error("Market analysis error — %s", err_msg)
            summary["errors"].append(err_msg)

    # ── 4. Check exits on open positions ──────────────────────────
    logger.info("Step 4/4: Checking exit conditions…")
    try:
        trader.check_and_exit_positions()
    except Exception as e:
        logger.error("Exit check failed: %s", e)
        summary["errors"].append(f"exit: {e}")

    # ── 5. Export JSON for Streamlit Cloud ────────────────────────
    try:
        from exporter import export_all
        export_all()
        logger.info("Data exported to data/ for Streamlit Cloud")
    except Exception as e:
        logger.warning("Data export failed (non-critical): %s", e)

    elapsed = round(time.time() - t0, 1)
    logger.info("=" * 55)
    logger.info("  Cycle complete in %.1fs", elapsed)
    logger.info("  Markets: %d | Signals: %d | Trades: %d | Errors: %d",
                summary["markets_scanned"], summary["signals_found"],
                summary["trades_executed"], len(summary["errors"]))
    if summary["errors"]:
        for e in summary["errors"]:
            logger.warning("  Error: %s", e)
    logger.info("=" * 55)
    return summary


if __name__ == "__main__":
    result = run_one_cycle()
    # Exit with error code if any errors occurred (useful for GitHub Actions)
    if result["errors"] and result["markets_scanned"] == 0:
        sys.exit(1)
    sys.exit(0)
