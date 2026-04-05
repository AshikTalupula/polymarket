"""
PolyEdge AI — Terminal Dashboard
Live status view using the Rich library. Refreshes every 30 seconds.
"""
import time
import logging
from datetime import datetime, timezone

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.columns import Columns
from rich import box

import config
import database as db
import risk_manager as rm

logger = logging.getLogger(__name__)

console = Console()

# Module-level state injected by main.py
_system_status: dict[str, str] = {}
_latest_signals: list[dict]    = []
_latest_headlines: list        = []


def update_status(key: str, value: str):
    _system_status[key] = value


def push_signal(signal_dict: dict):
    _latest_signals.insert(0, signal_dict)
    del _latest_signals[10:]


def push_headlines(headlines: list):
    global _latest_headlines
    _latest_headlines = headlines[:10]


# ─── Panel Builders ───────────────────────────────────────────────────────────

def _build_header() -> Panel:
    mode = "[bold red]🔴 LIVE[/]" if not config.DRY_RUN else "[bold yellow]🟡 DRY RUN[/]"
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    txt  = Text.from_markup(
        f"  PolyEdge AI — Autonomous Polymarket Trader  |  {mode}  |  {now}  "
    )
    return Panel(txt, style="bold blue", box=box.DOUBLE_EDGE)


def _build_capital_panel() -> Panel:
    capital   = rm.get_current_capital()
    daily_pnl = db.get_daily_pnl()
    pnl_color = "green" if daily_pnl >= 0 else "red"
    perf      = db.get_latest_performance()

    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("Key",   style="dim")
    table.add_column("Value", style="bold")

    table.add_row("💰 Current Capital",  f"[bold green]${capital:.4f}[/]")
    table.add_row("📈 Daily P&L",        f"[{pnl_color}]${daily_pnl:+.4f}[/]")
    table.add_row("📊 Total Trades",
                  str(perf["trades_placed"]) if perf else "—")
    table.add_row("🏆 Win Rate",
                  f"{perf['win_rate']*100:.1f}%" if perf else "—")

    open_trades = db.get_open_trades()
    table.add_row("📂 Open Positions",   str(len(open_trades)))
    table.add_row("🔑 Mode",
                  "DRY RUN" if config.DRY_RUN else "LIVE TRADING")

    return Panel(table, title="[bold cyan]Account Overview[/]", box=box.ROUNDED)


def _build_positions_panel() -> Panel:
    open_trades = db.get_open_trades()
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    table.add_column("Market",    max_width=35)
    table.add_column("Dir",       width=8)
    table.add_column("Entry",     width=8)
    table.add_column("Size",      width=8)
    table.add_column("Status",    width=10)
    table.add_column("Opened",    width=18)

    for t in open_trades[:6]:
        q     = t["market_question"] or t["market_id"]
        short = (q[:33] + "…") if len(q) > 34 else q
        dir_  = t.get("direction", "")
        color = "green" if "YES" in dir_ else "red"
        table.add_row(
            short,
            f"[{color}]{dir_}[/]",
            f"{t['entry_price']:.3f}",
            f"${t['size_usdc']:.2f}",
            t.get("status", "OPEN"),
            t.get("timestamp", "")[:16],
        )

    if not open_trades:
        table.add_row("[dim]No open positions[/]", "", "", "", "", "")

    return Panel(table, title="[bold cyan]Open Positions[/]", box=box.ROUNDED)


def _build_signals_panel() -> Panel:
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    table.add_column("Time",   width=8)
    table.add_column("Signal", width=18)
    table.add_column("Edge",   width=8)
    table.add_column("Conf",   width=8)
    table.add_column("Market", max_width=40)

    recent = db.get_recent_signals(5)
    for s in recent:
        stype  = s.get("direction", "?")
        acted  = s.get("acted_on", 0)
        color  = "green" if "BUY_YES" in stype or "SHOCK" in stype else (
                 "red" if "BUY_NO" in stype else "dim")
        acted_icon = "✅" if acted else "⏭"
        table.add_row(
            s.get("timestamp", "")[-8:16],
            f"[{color}]{acted_icon} {stype}[/]",
            f"{s.get('edge', 0):+.1f}%",
            s.get("confidence", "?"),
            (s.get("market_question", "")[:38] + "…")
            if len(s.get("market_question", "")) > 39 else s.get("market_question", ""),
        )

    if not recent:
        table.add_row("[dim]No signals yet[/]", "", "", "", "")

    return Panel(table, title="[bold cyan]Last 5 Signals[/]", box=box.ROUNDED)


def _build_trades_panel() -> Panel:
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    table.add_column("Time",  width=8)
    table.add_column("Dir",   width=8)
    table.add_column("Entry", width=8)
    table.add_column("PnL",   width=10)
    table.add_column("Market", max_width=38)

    recent = db.get_recent_trades(5)
    for t in recent:
        pnl = t.get("pnl")
        pnl_str = f"${pnl:+.4f}" if pnl is not None else "Open"
        pnl_color = "green" if pnl and pnl > 0 else ("red" if pnl and pnl < 0 else "cyan")
        dir_ = t.get("direction", "?")
        dir_color = "green" if "YES" in dir_ else "red"
        table.add_row(
            t.get("timestamp", "")[-8:16],
            f"[{dir_color}]{dir_}[/]",
            f"{t['entry_price']:.3f}",
            f"[{pnl_color}]{pnl_str}[/]",
            (t.get("market_question", "")[:36] + "…")
            if len(t.get("market_question", "")) > 37 else t.get("market_question", ""),
        )
    if not recent:
        table.add_row("[dim]No trades yet[/]", "", "", "", "")

    return Panel(table, title="[bold cyan]Last 5 Trades[/]", box=box.ROUNDED)


def _build_news_panel() -> Panel:
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column("Score", width=6, style="dim")
    table.add_column("Source", width=14, style="bold")
    table.add_column("Headline", max_width=70)

    for h in (_latest_headlines or [])[:10]:
        score  = getattr(h, "total_score", 0)
        source = getattr(h, "source", "?")[:13]
        title  = getattr(h, "title", "?")[:70]
        table.add_row(f"{score:.2f}", source, title)

    if not _latest_headlines:
        table.add_row("—", "—", "[dim]No headlines yet — waiting for news refresh[/]")

    return Panel(table, title="[bold cyan]News Feed (Last 10 Headlines)[/]", box=box.ROUNDED)


def _build_status_panel() -> Panel:
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("Loop",    style="dim", width=22)
    table.add_column("Status",  style="bold")

    defaults = {
        "News Engine (3min)":      "⏳ Waiting…",
        "Market Scanner (10min)":  "⏳ Waiting…",
        "AI Analyst (10min)":      "⏳ Waiting…",
        "Exit Checker (5min)":     "⏳ Waiting…",
        "Order Cleanup (30min)":   "⏳ Waiting…",
        "Perf Snapshot (1hr)":     "⏳ Waiting…",
    }
    for k, v in defaults.items():
        status = _system_status.get(k, v)
        color  = "green" if "✅" in status else ("red" if "❌" in status else "yellow")
        table.add_row(k, f"[{color}]{status}[/]")

    return Panel(table, title="[bold cyan]System Status[/]", box=box.ROUNDED)


# ─── Main Render Loop ──────────────────────────────────────────────────────────

def build_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="top",    size=10),
        Layout(name="mid",    size=14),
        Layout(name="news",   size=14),
        Layout(name="status", size=12),
    )
    layout["top"].split_row(
        Layout(name="capital",   ratio=1),
        Layout(name="positions", ratio=2),
    )
    layout["mid"].split_row(
        Layout(name="signals", ratio=1),
        Layout(name="trades",  ratio=1),
    )
    return layout


def render_once():
    layout = build_layout()
    layout["header"].update(_build_header())
    layout["capital"].update(_build_capital_panel())
    layout["positions"].update(_build_positions_panel())
    layout["signals"].update(_build_signals_panel())
    layout["trades"].update(_build_trades_panel())
    layout["news"].update(_build_news_panel())
    layout["status"].update(_build_status_panel())
    return layout


def run_dashboard():
    """Blocking dashboard loop — run in main thread."""
    with Live(render_once(), console=console, refresh_per_second=1,
              screen=True) as live:
        while True:
            try:
                live.update(render_once())
            except Exception as e:
                logger.error("Dashboard render error: %s", e)
            time.sleep(config.DASHBOARD_REFRESH_SECONDS)
