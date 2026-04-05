"""
PolyEdge AI — Data Exporter
Reads from SQLite and writes JSON snapshots to data/ folder.
These JSON files are committed to the GitHub repo so Streamlit Cloud
can read them without a separate cloud database.

Architecture:
  GitHub Actions → run_cycle.py → exporter.py → data/*.json (committed to repo)
  Streamlit Cloud → streamlit_app.py → reads data/*.json from repo
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone, date

logger = logging.getLogger(__name__)

# Resolve paths relative to this file
_HERE     = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.dirname(_HERE)          # project root
DATA_DIR  = os.path.join(_ROOT, "data")
DB_PATH   = os.path.join(_HERE, "polyedge.db")

# How many records to keep in the rolling exports
MAX_SIGNALS = 100
MAX_TRADES  = 200


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _write_json(filename: str, obj):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    logger.info("Exported %s (%d bytes)", filename, os.path.getsize(path))


def _read_db(sql: str, params=()):
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception as e:
        logger.warning("DB read error: %s", e)
        return []
    finally:
        conn.close()


def export_all():
    """
    Export all relevant DB tables to JSON files in data/.
    Called at the end of each scan cycle by run_cycle.py.
    """
    _ensure_data_dir()

    # ── 1. Recent signals (last MAX_SIGNALS) ──────────────────────────────────
    signals = _read_db(
        "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (MAX_SIGNALS,)
    )
    _write_json("signals.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count":      len(signals),
        "records":    signals,
    })

    # ── 2. All trades (open + recent closed) ──────────────────────────────────
    trades = _read_db(
        "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (MAX_TRADES,)
    )
    _write_json("trades.json", {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count":      len(trades),
        "records":    trades,
    })

    # ── 3. Portfolio snapshot ──────────────────────────────────────────────────
    open_pos   = _read_db("SELECT COUNT(*) as n FROM trades WHERE status='OPEN'")
    closed_pos = _read_db("SELECT COUNT(*) as n, "
                          "SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as w, "
                          "COALESCE(SUM(pnl),0) as total_pnl, "
                          "COALESCE(SUM(fee_paid),0) as total_fees "
                          "FROM trades WHERE status='CLOSED'")
    today_pnl  = _read_db(
        "SELECT COALESCE(SUM(pnl),0) as t FROM trades "
        "WHERE status='CLOSED' AND date(timestamp)=?",
        (date.today().isoformat(),)
    )
    market_scan = _read_db(
        """SELECT DISTINCT market_question, market_id, MAX(timestamp) as latest,
                   ai_probability, market_price, edge, confidence
            FROM signals GROUP BY market_id ORDER BY latest DESC LIMIT 15"""
    )

    cp  = closed_pos[0] if closed_pos else {}
    _write_json("portfolio.json", {
        "updated_at":       datetime.now(timezone.utc).isoformat(),
        "open_positions":   open_pos[0]["n"] if open_pos else 0,
        "total_closed":     cp.get("n", 0),
        "wins":             cp.get("w", 0),
        "total_pnl":        float(cp.get("total_pnl", 0)),
        "today_pnl":        float(today_pnl[0]["t"]) if today_pnl else 0.0,
        "total_fees":       float(cp.get("total_fees", 0)),
        "market_scan":      market_scan,
    })

    logger.info("Data export complete → data/ (signals=%d trades=%d)",
                len(signals), len(trades))
    return True
