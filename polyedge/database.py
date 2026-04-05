"""
PolyEdge AI — Database Module
SQLite logging for signals, trades, and performance snapshots.
"""
import sqlite3
import logging
from datetime import date, datetime
from typing import Optional
import config

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                market_question TEXT NOT NULL,
                market_id    TEXT NOT NULL,
                ai_probability REAL,
                market_price REAL,
                edge         REAL,
                confidence   TEXT,
                direction    TEXT,
                acted_on     INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS trades (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                market_id    TEXT NOT NULL,
                market_question TEXT,
                direction    TEXT,
                entry_price  REAL,
                size_usdc    REAL,
                order_id     TEXT,
                status       TEXT DEFAULT 'OPEN',
                exit_price   REAL,
                pnl          REAL,
                fee_paid     REAL,
                token_id     TEXT,
                category     TEXT
            );

            CREATE TABLE IF NOT EXISTS performance (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                date             TEXT NOT NULL,
                snapshot_time    TEXT NOT NULL,
                starting_capital REAL,
                ending_capital   REAL,
                trades_placed    INTEGER,
                win_rate         REAL,
                total_fees_paid  REAL,
                net_pnl          REAL
            );

            CREATE TABLE IF NOT EXISTS news_headlines (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                url_hash     TEXT UNIQUE,
                title        TEXT,
                url          TEXT,
                source       TEXT,
                credibility  REAL,
                market_id    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_signals_market ON signals(market_id);
            CREATE INDEX IF NOT EXISTS idx_trades_market   ON trades(market_id);
            CREATE INDEX IF NOT EXISTS idx_trades_status   ON trades(status);
        """)
        conn.commit()
        logger.info("Database initialised at %s", config.DB_PATH)
    finally:
        conn.close()


# ─── Signals ─────────────────────────────────────────────────────────────────

def log_signal(market_question: str, market_id: str, ai_probability: float,
               market_price: float, edge: float, confidence: str,
               direction: str, acted_on: bool = False):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO signals
               (timestamp, market_question, market_id, ai_probability, market_price,
                edge, confidence, direction, acted_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), market_question, market_id,
             ai_probability, market_price, edge, confidence, direction,
             int(acted_on))
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to log signal: %s", e)
    finally:
        conn.close()


def get_recent_signals(limit: int = 10) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Trades ──────────────────────────────────────────────────────────────────

def log_trade(market_id: str, market_question: str, direction: str,
              entry_price: float, size_usdc: float, order_id: str,
              token_id: str = "", category: str = "") -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO trades
               (timestamp, market_id, market_question, direction, entry_price,
                size_usdc, order_id, status, fee_paid, token_id, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)""",
            (datetime.utcnow().isoformat(), market_id, market_question,
             direction, entry_price, size_usdc, order_id,
             round(size_usdc * config.POLYMARKET_FEE_PCT / 100, 4),
             token_id, category)
        )
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error("Failed to log trade: %s", e)
        return -1
    finally:
        conn.close()


def update_trade_exit(trade_id: int, exit_price: float, pnl: float,
                      status: str = "CLOSED"):
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE trades SET exit_price=?, pnl=?, status=?
               WHERE id=?""",
            (exit_price, pnl, status, trade_id)
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to update trade exit: %s", e)
    finally:
        conn.close()


def get_open_trades() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='OPEN'"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_trades(limit: int = 10) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_daily_pnl() -> float:
    conn = get_connection()
    try:
        today = date.today().isoformat()
        row = conn.execute(
            """SELECT COALESCE(SUM(pnl), 0) as total
               FROM trades WHERE date(timestamp)=? AND status='CLOSED'""",
            (today,)
        ).fetchone()
        return row["total"] if row else 0.0
    finally:
        conn.close()


def count_open_trades_by_category(category: str) -> float:
    """Return total USDC exposure in a given category for open trades."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT COALESCE(SUM(size_usdc), 0) as total
               FROM trades WHERE status='OPEN' AND category=?""",
            (category,)
        ).fetchone()
        return row["total"] if row else 0.0
    finally:
        conn.close()


# ─── Performance Snapshots ───────────────────────────────────────────────────

def log_performance_snapshot(starting_capital: float, ending_capital: float):
    conn = get_connection()
    try:
        today = date.today().isoformat()
        now = datetime.utcnow().isoformat()

        # Calculate stats
        rows_today = conn.execute(
            "SELECT pnl FROM trades WHERE date(timestamp)=? AND status='CLOSED'",
            (today,)
        ).fetchall()
        trades_placed = len(rows_today)
        wins = sum(1 for r in rows_today if r["pnl"] and r["pnl"] > 0)
        win_rate = wins / trades_placed if trades_placed else 0.0

        fees = conn.execute(
            "SELECT COALESCE(SUM(fee_paid),0) FROM trades WHERE date(timestamp)=?",
            (today,)
        ).fetchone()[0]

        net_pnl = ending_capital - starting_capital

        conn.execute(
            """INSERT INTO performance
               (date, snapshot_time, starting_capital, ending_capital,
                trades_placed, win_rate, total_fees_paid, net_pnl)
               VALUES (?,?,?,?,?,?,?,?)""",
            (today, now, starting_capital, ending_capital,
             trades_placed, win_rate, fees, net_pnl)
        )
        conn.commit()
        logger.info("Performance snapshot logged. Capital: $%.2f | PnL: $%.2f",
                    ending_capital, net_pnl)
    except Exception as e:
        logger.error("Failed to log performance: %s", e)
    finally:
        conn.close()


def get_latest_performance() -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM performance ORDER BY snapshot_time DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
