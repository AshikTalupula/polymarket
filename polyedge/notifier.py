"""
PolyEdge AI — Notifier
Lightweight in-process notification system.
Events are stored in a queue and surfaced via:
  1. The Streamlit dashboard (reads from SQLite)
  2. A simple desktop toast (win10toast / plyer) if available
  3. A plain-text notification log file
"""
import logging
import os
import queue
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Thread-safe notification queue consumed by dashboard
_notification_queue: queue.Queue = queue.Queue(maxsize=100)

# Notification log file
_LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "notifications.log"
)

# ── Optional desktop toast support ──────────────────────────────────────────
try:
    from plyer import notification as _plyer_notif
    _PLYER_AVAILABLE = True
except ImportError:
    _PLYER_AVAILABLE = False

try:
    from win10toast import ToastNotifier
    _toaster = ToastNotifier()
    _WIN_TOAST_AVAILABLE = True
except Exception:
    _WIN_TOAST_AVAILABLE = False
    _toaster = None


# ─── Public API ──────────────────────────────────────────────────────────────

def notify(title: str, message: str, level: str = "INFO"):
    """
    Send a notification via all available channels.

    Args:
        title:   Short title (e.g. "Trade Placed")
        message: Full message body
        level:   INFO | WARNING | ALERT
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    payload = {
        "timestamp": now,
        "title":     title,
        "message":   message,
        "level":     level,
    }

    # 1. Enqueue for dashboard
    try:
        _notification_queue.put_nowait(payload)
    except queue.Full:
        _notification_queue.get_nowait()  # drop oldest
        _notification_queue.put_nowait(payload)

    # 2. Write to notification log
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{now}] [{level}] {title}: {message}\n")
    except Exception as e:
        logger.debug("Notification log write failed: %s", e)

    # 3. Windows toast notification (best effort)
    if _WIN_TOAST_AVAILABLE and _toaster:
        try:
            _toaster.show_toast(
                title=f"PolyEdge AI — {title}",
                msg=message[:200],
                duration=5,
                threaded=True,
            )
        except Exception as e:
            logger.debug("Windows toast failed: %s", e)
    elif _PLYER_AVAILABLE:
        try:
            _plyer_notif.notify(
                title=f"PolyEdge AI — {title}",
                message=message[:200],
                app_name="PolyEdge AI",
                timeout=5,
            )
        except Exception as e:
            logger.debug("Plyer notification failed: %s", e)

    # 4. Logger
    log_fn = logger.warning if level == "WARNING" else \
             logger.critical if level == "ALERT" else logger.info
    log_fn("📢 [%s] %s: %s", level, title, message)


def get_recent_notifications(n: int = 20) -> list[dict]:
    """Drain up to n notifications from the queue (non-blocking peek)."""
    results = []
    temp = []
    while not _notification_queue.empty() and len(results) < n:
        item = _notification_queue.get_nowait()
        results.append(item)
        temp.append(item)
    # Put them back
    for item in temp:
        try:
            _notification_queue.put_nowait(item)
        except queue.Full:
            break
    return results


# ─── Convenience wrappers ─────────────────────────────────────────────────────

def notify_trade_placed(market: str, direction: str, size: float,
                        price: float, order_id: str):
    notify(
        title="Trade Placed",
        message=(
            f"{direction} | {market[:50]} | "
            f"${size:.2f} @ {price:.4f} | Order: {order_id[:16]}"
        ),
        level="INFO",
    )


def notify_trade_closed(market: str, pnl: float, reason: str):
    emoji = "✅" if pnl > 0 else "❌"
    notify(
        title=f"{emoji} Position Closed ({reason})",
        message=f"{market[:50]} | P&L: ${pnl:+.4f}",
        level="INFO" if pnl >= 0 else "WARNING",
    )


def notify_shock_detected(market: str, n_headlines: int):
    notify(
        title="⚡ Breaking News Shock",
        message=f"{n_headlines} headlines in 10min | Market: {market[:60]}",
        level="WARNING",
    )


def notify_risk_alert(reason: str):
    notify(
        title="🛑 Risk Alert",
        message=reason,
        level="ALERT",
    )


def notify_daily_loss_limit():
    notify(
        title="🛑 Daily Loss Limit Hit",
        message=f"Trading suspended for the day. Limit: ${abs(__import__('config').DAILY_LOSS_LIMIT):.2f}",
        level="ALERT",
    )
