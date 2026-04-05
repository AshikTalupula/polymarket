"""
PolyEdge AI — Main Entry Point
Orchestrates all loops using APScheduler and runs the terminal dashboard.
"""
import logging
import sys
import os
import threading

# ── Ensure polyedge/ is on the import path ─────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

import config
import database as db
import dashboard

logger = logging.getLogger(__name__)


# ─── Lazy singletons ─────────────────────────────────────────────────────────
# Imported here to avoid circular dependency issues at module level

def _get_instances():
    from news_engine     import NewsAggregator
    from ai_analyst      import PolyAnalyst
    from signal_detector import SignalDetector
    from trade_executor  import TradeExecutor
    import market_scanner

    news_agg  = NewsAggregator()
    ai_analyst = PolyAnalyst()
    sig_det    = SignalDetector()
    trader     = TradeExecutor()

    return news_agg, ai_analyst, sig_det, trader, market_scanner


# ─── Scheduled Jobs ───────────────────────────────────────────────────────────

def job_refresh_news(news_agg):
    dashboard.update_status("News Engine (3min)", "🔄 Running…")
    try:
        news_agg.refresh_all_sources()
        heads = news_agg.get_all_recent_headlines(10)
        dashboard.push_headlines(heads)
        dashboard.update_status("News Engine (3min)", "✅ OK")
    except Exception as e:
        logger.error("News refresh error: %s", e)
        dashboard.update_status("News Engine (3min)", f"❌ {str(e)[:30]}")


def job_scan_and_analyze(market_scanner, news_agg, ai_analyst, sig_det, trader):
    dashboard.update_status("Market Scanner (10min)", "🔄 Scanning…")
    dashboard.update_status("AI Analyst (10min)", "🔄 Analysing…")
    try:
        markets = market_scanner.scan()
        dashboard.update_status("Market Scanner (10min)",
                                f"✅ {len(markets)} markets")

        signals_found = 0
        for market in markets:
            try:
                # Get news context for this market
                news_ctx = news_agg.get_news_for_market(market)

                # Standard AI analysis
                analysis = ai_analyst.analyze(market, news_ctx)
                if analysis is None:
                    continue

                # Check for shock → escalate to shock analysis if needed
                if news_ctx.is_shock:
                    shock = ai_analyst.analyze_shock(
                        market, news_ctx, analysis.true_probability
                    )
                    if shock:
                        sig = sig_det.evaluate_shock(market, shock, analysis)
                        if sig:
                            signals_found += 1
                            dashboard.push_signal({
                                "market_question": sig.market_question,
                                "signal_type":     sig.signal_type,
                                "edge":            sig.edge,
                                "confidence":      sig.confidence,
                            })
                            if sig.is_strong:
                                trader.execute_signal(sig)
                        continue  # Skip standard evaluation for this market

                # Standard signal evaluation
                sig = sig_det.evaluate(market, analysis)
                if sig:
                    signals_found += 1
                    dashboard.push_signal({
                        "market_question": sig.market_question,
                        "signal_type":     sig.signal_type,
                        "edge":            sig.edge,
                        "confidence":      sig.confidence,
                    })
                    if sig.is_strong:
                        trader.execute_signal(sig)

            except Exception as inner_err:
                logger.error("Error analysing market '%s': %s",
                             market.get("question", "?")[:40], inner_err)

        dashboard.update_status("AI Analyst (10min)",
                                f"✅ {signals_found} signal(s) found")

    except Exception as e:
        logger.error("Scan+analyse job error: %s", e)
        dashboard.update_status("Market Scanner (10min)", f"❌ {str(e)[:30]}")
        dashboard.update_status("AI Analyst (10min)",     f"❌ {str(e)[:30]}")


def job_exit_positions(trader):
    dashboard.update_status("Exit Checker (5min)", "🔄 Checking…")
    try:
        trader.check_and_exit_positions()
        dashboard.update_status("Exit Checker (5min)", "✅ OK")
    except Exception as e:
        logger.error("Exit check error: %s", e)
        dashboard.update_status("Exit Checker (5min)", f"❌ {str(e)[:30]}")


def job_cancel_stale(trader):
    dashboard.update_status("Order Cleanup (30min)", "🔄 Cleaning…")
    try:
        trader.cancel_stale_orders()
        dashboard.update_status("Order Cleanup (30min)", "✅ OK")
    except Exception as e:
        logger.error("Cancel stale orders error: %s", e)
        dashboard.update_status("Order Cleanup (30min)", f"❌ {str(e)[:30]}")


def job_log_performance():
    dashboard.update_status("Perf Snapshot (1hr)", "🔄 Logging…")
    try:
        import risk_manager as rm
        cap = rm.get_current_capital()
        db.log_performance_snapshot(
            starting_capital=config.CAPITAL_TOTAL,
            ending_capital=cap,
        )
        dashboard.update_status("Perf Snapshot (1hr)", "✅ OK")
    except Exception as e:
        logger.error("Performance snapshot error: %s", e)
        dashboard.update_status("Perf Snapshot (1hr)", f"❌ {str(e)[:30]}")


# ─── APScheduler Listener ─────────────────────────────────────────────────────

def _scheduler_listener(event):
    if event.exception:
        logger.error("Scheduler job crashed: %s — %s",
                     event.job_id, event.exception)


# ─── Startup ──────────────────────────────────────────────────────────────────

def configure_logging():
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("polyedge.log", encoding="utf-8"),
        ],
    )


def main():
    configure_logging()
    logger.info("=" * 60)
    logger.info("  PolyEdge AI — Starting Up")
    logger.info("=" * 60)

    # Validate config
    warnings = config.validate_config()
    for w in warnings:
        logger.warning("CONFIG: %s", w)

    # Initialise database
    db.init_db()

    # Build singleton instances
    news_agg, ai_analyst, sig_det, trader, market_scanner = _get_instances()

    # ── APScheduler ─────────────────────────────────────────────────────
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_listener(_scheduler_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    # Every 3 min: news refresh
    scheduler.add_job(
        job_refresh_news,
        "interval", minutes=3, id="news_refresh",
        args=[news_agg],
        next_run_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    # Every 10 min: scan + analyse + signal
    scheduler.add_job(
        job_scan_and_analyze,
        "interval", minutes=10, id="scan_analyze",
        args=[market_scanner, news_agg, ai_analyst, sig_det, trader],
        next_run_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    # Every 5 min: exit positions
    scheduler.add_job(
        job_exit_positions,
        "interval", minutes=5, id="exit_positions",
        args=[trader],
    )

    # Every 30 min: cancel stale orders
    scheduler.add_job(
        job_cancel_stale,
        "interval", minutes=30, id="cancel_stale",
        args=[trader],
    )

    # Every 1 hour: performance snapshot
    scheduler.add_job(
        job_log_performance,
        "interval", hours=1, id="perf_snapshot",
    )

    scheduler.start()
    logger.info("APScheduler started — all loops running.")

    # ── Dashboard (blocking, runs in main thread) ─────────────────────
    try:
        dashboard.run_dashboard()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — shutting down.")
    finally:
        scheduler.shutdown(wait=False)
        logger.info("PolyEdge AI stopped.")


if __name__ == "__main__":
    main()
