"""
PolyEdge AI — Streamlit Dashboard
Full web UI for monitoring the trading bot.
Deploy free at: streamlit.io/cloud
"""
import sys
import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta, date

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# ── path setup so we can import config / database
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "polyedge"))

import config
import database as db

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PolyEdge AI — Polymarket Bot",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* Dark gradient background */
.stApp {
    background: linear-gradient(135deg, #0a0e1a 0%, #0d1b35 50%, #0a1628 100%);
}

/* Metric cards */
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, rgba(0,212,255,0.08), rgba(0,100,200,0.05));
    border: 1px solid rgba(0,212,255,0.2);
    border-radius: 12px;
    padding: 16px 20px;
    backdrop-filter: blur(10px);
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1b35, #091020);
    border-right: 1px solid rgba(0,212,255,0.15);
}

/* Headers */
h1 { color: #00d4ff; font-weight: 900; letter-spacing: -0.5px; }
h2 { color: #7eb8f7; font-weight: 700; }
h3 { color: #a8c8f0; font-weight: 600; }

/* Dataframe */
div[data-testid="stDataFrame"] {
    border: 1px solid rgba(0,212,255,0.15);
    border-radius: 8px;
}

/* Status badge helpers */
.status-live   { color: #ff4444; font-weight: 700; }
.status-dry    { color: #ffaa00; font-weight: 700; }
.edge-positive { color: #00ff88; font-weight: 600; }
.edge-negative { color: #ff4444; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ PolyEdge AI")
    mode_text = "🔴 LIVE TRADING" if not config.DRY_RUN else "🟡 DRY RUN MODE"
    st.markdown(f"**Mode:** {mode_text}")
    st.markdown(f"**Model:** {config.GROQ_MODEL}")
    st.markdown(f"**Min Edge:** {config.MIN_EDGE_AFTER_FEE}%")
    st.markdown(f"**Max Positions:** {config.MAX_OPEN_POSITIONS}")
    st.markdown(f"**Kelly Fraction:** {config.KELLY_FRACTION}")
    st.markdown("---")

    refresh_rate = st.selectbox(
        "Auto-refresh interval",
        [15, 30, 60, 120],
        index=1,
        format_func=lambda x: f"{x}s"
    )
    auto_refresh = st.checkbox("Enable auto-refresh", value=True)

    st.markdown("---")
    st.markdown("**⚠️ Disclaimer**")
    st.caption(
        "US persons cannot use Polymarket. Paper trade first. "
        "This software is for educational purposes. "
        "Trading prediction markets carries significant risk."
    )


# ─── Header ───────────────────────────────────────────────────────────────────
col_title, col_time = st.columns([3, 1])
with col_title:
    st.markdown("# ⚡ PolyEdge AI")
    st.caption("Autonomous Polymarket Trading System — Real-Time Dashboard")
with col_time:
    st.markdown(f"**{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}**")
    if auto_refresh:
        st.caption(f"Auto-refreshing every {refresh_rate}s")

st.markdown("---")


# ─── Helper Functions ─────────────────────────────────────────────────────────

@st.cache_data(ttl=10)
def cached_open_trades():
    return db.get_open_trades()

@st.cache_data(ttl=10)
def cached_recent_trades(n=20):
    return db.get_recent_trades(n)

@st.cache_data(ttl=10)
def cached_recent_signals(n=20):
    return db.get_recent_signals(n)

@st.cache_data(ttl=30)
def cached_performance():
    return db.get_latest_performance()

@st.cache_data(ttl=30)
def cached_daily_pnl():
    return db.get_daily_pnl()

def get_capital():
    try:
        import risk_manager as rm
        return rm.get_current_capital()
    except Exception:
        return config.CAPITAL_TOTAL


# ─── Top KPI Row ─────────────────────────────────────────────────────────────

open_trades  = cached_open_trades()
daily_pnl    = cached_daily_pnl()
perf         = cached_performance()
capital      = get_capital()
pnl_vs_start = capital - config.CAPITAL_TOTAL

k1, k2, k3, k4, k5, k6 = st.columns(6)

with k1:
    st.metric("💰 Capital", f"${capital:.2f}",
              delta=f"{pnl_vs_start:+.2f}")
with k2:
    color_delta = daily_pnl
    st.metric("📈 Daily P&L", f"${daily_pnl:+.4f}")
with k3:
    st.metric("📂 Open Positions",
              len(open_trades),
              delta=f"max {config.MAX_OPEN_POSITIONS}")
with k4:
    win_rate = perf["win_rate"] if perf else 0
    st.metric("🏆 Win Rate", f"{win_rate*100:.1f}%")
with k5:
    total_trades = perf["trades_placed"] if perf else 0
    st.metric("📊 Trades (today)", total_trades)
with k6:
    fees = perf["total_fees_paid"] if perf else 0
    st.metric("💸 Fees Paid", f"${fees:.4f}")

st.markdown("---")


# ─── Charts Row ───────────────────────────────────────────────────────────────

col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.subheader("📊 P&L History")
    trades_df = pd.DataFrame(cached_recent_trades(100))
    if not trades_df.empty and "pnl" in trades_df.columns:
        trades_df = trades_df.dropna(subset=["pnl"])
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])
        trades_df = trades_df.sort_values("timestamp")
        trades_df["cumulative_pnl"] = trades_df["pnl"].cumsum()

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=trades_df["timestamp"],
            y=trades_df["cumulative_pnl"],
            mode="lines+markers",
            line=dict(color="#00d4ff", width=2),
            fill="tozeroy",
            fillcolor="rgba(0,212,255,0.1)",
            name="Cumulative P&L",
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#7eb8f7"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)",
                       tickprefix="$"),
            margin=dict(l=0, r=0, t=0, b=0),
            height=260,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No closed trades yet — P&L chart will appear here.")

with col_chart2:
    st.subheader("🎯 Signal Distribution")
    sigs_df = pd.DataFrame(cached_recent_signals(100))
    if not sigs_df.empty and "direction" in sigs_df.columns:
        counts = sigs_df["direction"].value_counts().reset_index()
        counts.columns = ["Signal", "Count"]
        colors = {
            "STRONG_BUY_YES": "#00ff88",
            "BUY_YES":        "#00cc66",
            "STRONG_BUY_NO":  "#ff4444",
            "BUY_NO":         "#cc2222",
            "SHOCK_TRADE":    "#ffaa00",
            "NO_TRADE":       "#555577",
        }
        fig2 = px.pie(
            counts, names="Signal", values="Count",
            color="Signal",
            color_discrete_map=colors,
            hole=0.45,
        )
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#7eb8f7"),
            legend=dict(font=dict(color="#7eb8f7")),
            margin=dict(l=10, r=10, t=10, b=10),
            height=260,
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No signals yet — chart will appear after first scan cycle.")

st.markdown("---")


# ─── Open Positions ───────────────────────────────────────────────────────────

st.subheader("📂 Open Positions")
if open_trades:
    op_df = pd.DataFrame(open_trades)
    display_cols = [c for c in
                    ["timestamp", "market_question", "direction",
                     "entry_price", "size_usdc", "category", "order_id"]
                    if c in op_df.columns]
    op_df["entry_price"] = op_df["entry_price"].map(lambda x: f"{x:.4f}")
    op_df["size_usdc"]   = op_df["size_usdc"].map(lambda x: f"${x:.2f}")
    st.dataframe(
        op_df[display_cols].rename(columns={
            "timestamp":       "Opened",
            "market_question": "Market",
            "direction":       "Direction",
            "entry_price":     "Entry",
            "size_usdc":       "Size",
            "category":        "Category",
            "order_id":        "Order ID",
        }),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No open positions.")

st.markdown("---")


# ─── Recent Signals ───────────────────────────────────────────────────────────

st.subheader("🎯 Recent Signals")
sigs_df = pd.DataFrame(cached_recent_signals(15))
if not sigs_df.empty:
    display_cols = [c for c in
                    ["timestamp", "market_question", "direction",
                     "edge", "confidence", "ai_probability",
                     "market_price", "acted_on"]
                    if c in sigs_df.columns]
    sigs_df["edge"]           = sigs_df["edge"].map(lambda x: f"{x:+.1f}%")
    sigs_df["ai_probability"] = sigs_df["ai_probability"].map(lambda x: f"{x:.1f}%")
    sigs_df["market_price"]   = sigs_df["market_price"].map(lambda x: f"{x:.1f}%")
    sigs_df["acted_on"]       = sigs_df["acted_on"].map(lambda x: "✅" if x else "⏭")
    st.dataframe(
        sigs_df[display_cols].rename(columns={
            "timestamp":       "Time",
            "market_question": "Market",
            "direction":       "Signal",
            "edge":            "Edge",
            "confidence":      "Confidence",
            "ai_probability":  "AI Prob",
            "market_price":    "Mkt Price",
            "acted_on":        "Traded",
        }),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No signals yet — check back after the first scan cycle (10 min).")

st.markdown("---")


# ─── Trade History ────────────────────────────────────────────────────────────

st.subheader("📜 Trade History (Last 20)")
trades_df = pd.DataFrame(cached_recent_trades(20))
if not trades_df.empty:
    display_cols = [c for c in
                    ["timestamp", "market_question", "direction",
                     "entry_price", "exit_price", "size_usdc",
                     "pnl", "fee_paid", "status"]
                    if c in trades_df.columns]

    def _color_pnl(val):
        if val is None or str(val) == "nan":
            return ""
        try:
            v = float(str(val).replace("$",""))
            return f"color: {'#00ff88' if v > 0 else '#ff4444'}"
        except Exception:
            return ""

    trades_df["entry_price"] = trades_df["entry_price"].map(lambda x: f"{x:.4f}")
    trades_df["exit_price"]  = trades_df["exit_price"].map(
        lambda x: f"{x:.4f}" if x and str(x) != "nan" else "—"
    )
    trades_df["size_usdc"]   = trades_df["size_usdc"].map(lambda x: f"${x:.2f}")
    trades_df["pnl"]         = trades_df["pnl"].map(
        lambda x: f"${x:+.4f}" if x and str(x) != "nan" else "Open"
    )
    trades_df["fee_paid"]    = trades_df["fee_paid"].map(lambda x: f"${x:.4f}")

    st.dataframe(
        trades_df[display_cols].rename(columns={
            "timestamp":       "Time",
            "market_question": "Market",
            "direction":       "Direction",
            "entry_price":     "Entry",
            "exit_price":      "Exit",
            "size_usdc":       "Size",
            "pnl":             "P&L",
            "fee_paid":        "Fee",
            "status":          "Status",
        }),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No trades placed yet.")

st.markdown("---")

# ─── Footer + Auto-refresh ────────────────────────────────────────────────────
st.caption(
    "PolyEdge AI © 2025 — For educational purposes only. "
    "US persons cannot use Polymarket. Always paper trade first."
)

if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
