"""
PolyEdge AI — Streamlit Dashboard
Reads directly from SQLite — no heavy bot imports, starts instantly.
Deploy free at: streamlit.io/cloud
"""
import os
import sys
import sqlite3
import time
from datetime import datetime, timezone, date

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dotenv import load_dotenv

load_dotenv()

# ─── Config (read directly — no bot imports) ──────────────────────────────────
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "polyedge", "polyedge.db"
)
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "100.0"))
DRY_RUN          = os.getenv("DRY_RUN", "true").lower() == "true"
GROQ_MODEL       = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_OPEN_POS     = int(os.getenv("MAX_OPEN_POSITIONS", "4"))
MIN_EDGE         = float(os.getenv("MIN_EDGE_AFTER_FEE", "7.0"))

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PolyEdge AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: linear-gradient(135deg, #0a0e1a 0%, #0d1b35 50%, #0a1628 100%); }
div[data-testid="metric-container"] {
    background: linear-gradient(135deg,rgba(0,212,255,.08),rgba(0,100,200,.05));
    border: 1px solid rgba(0,212,255,.2); border-radius:12px; padding:16px 20px;
}
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg,#0d1b35,#091020);
    border-right: 1px solid rgba(0,212,255,.15);
}
h1{color:#00d4ff;font-weight:900;} h2{color:#7eb8f7;font-weight:700;}
</style>
""", unsafe_allow_html=True)

# ─── DB helpers (raw SQLite — no bot dependency) ──────────────────────────────

def _conn():
    if not os.path.exists(DB_PATH):
        return None
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def _q(sql, params=()):
    c = _conn()
    if c is None:
        return []
    try:
        rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        c.close()

def db_ready():
    return os.path.exists(DB_PATH)

@st.cache_data(ttl=8)
def get_open_trades():
    return _q("SELECT * FROM trades WHERE status='OPEN' ORDER BY timestamp DESC")

@st.cache_data(ttl=8)
def get_recent_trades(n=20):
    return _q("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (n,))

@st.cache_data(ttl=8)
def get_recent_signals(n=20):
    return _q("SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (n,))

@st.cache_data(ttl=15)
def get_daily_pnl():
    today = date.today().isoformat()
    rows = _q("SELECT COALESCE(SUM(pnl),0) as t FROM trades WHERE date(timestamp)=? AND status='CLOSED'", (today,))
    return rows[0]["t"] if rows else 0.0

@st.cache_data(ttl=15)
def get_total_pnl():
    rows = _q("SELECT COALESCE(SUM(pnl),0) as t FROM trades WHERE status='CLOSED'")
    return rows[0]["t"] if rows else 0.0

@st.cache_data(ttl=15)
def get_stats():
    rows = _q("SELECT COUNT(*) as n, SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as w, COALESCE(SUM(fee_paid),0) as f FROM trades WHERE status='CLOSED'")
    if rows:
        n, w, f = rows[0]["n"] or 0, rows[0]["w"] or 0, rows[0]["f"] or 0
        return {"trades": n, "wins": w, "win_rate": (w/n if n else 0), "fees": f}
    return {"trades": 0, "wins": 0, "win_rate": 0.0, "fees": 0.0}

@st.cache_data(ttl=30)
def get_perf_history():
    return _q("SELECT * FROM performance ORDER BY snapshot_time DESC LIMIT 48")

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ PolyEdge AI")
    mode = "🟡 DRY RUN" if DRY_RUN else "🔴 LIVE"
    st.markdown(f"**Mode:** {mode}")
    st.markdown(f"**Model:** `{GROQ_MODEL}`")
    st.markdown(f"**Min Edge:** {MIN_EDGE}%")
    st.markdown(f"**Max Positions:** {MAX_OPEN_POS}")
    st.markdown("---")

    if not db_ready():
        st.warning("⚠️ Database not found.\nStart `main.py` first to generate data.")
    else:
        st.success("✅ Database connected")

    refresh = st.selectbox("Auto-refresh", [10, 30, 60], index=1,
                           format_func=lambda x: f"Every {x}s")
    auto = st.checkbox("Enable auto-refresh", value=True)

    st.markdown("---")
    st.caption("⚠️ US persons cannot use Polymarket. Paper trade first.")

# ─── Header ───────────────────────────────────────────────────────────────────
c1, c2 = st.columns([4, 1])
with c1:
    st.markdown("# ⚡ PolyEdge AI")
    st.caption("Autonomous Polymarket Trading System — Live Dashboard")
with c2:
    st.markdown(f"`{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`")

# ─── DB not ready banner ──────────────────────────────────────────────────────
if not db_ready():
    st.info("""
    **🚀 Bot not running yet.** Start it with:
    ```
    cd polyedge
    python main.py
    ```
    The dashboard will populate automatically once the first scan cycle runs (~1 min).
    """)
    if auto:
        time.sleep(refresh)
        st.rerun()
    st.stop()

st.divider()

# ─── KPI Metrics ──────────────────────────────────────────────────────────────
open_trades = get_open_trades()
daily_pnl   = get_daily_pnl()
total_pnl   = get_total_pnl()
stats       = get_stats()
current_cap = STARTING_CAPITAL + total_pnl

k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    st.metric("💰 Capital",    f"${current_cap:.2f}",    delta=f"{total_pnl:+.2f}")
with k2:
    st.metric("📈 Today P&L", f"${daily_pnl:+.4f}")
with k3:
    st.metric("📂 Open Pos",  len(open_trades),          delta=f"/ {MAX_OPEN_POS} max")
with k4:
    st.metric("🏆 Win Rate",  f"{stats['win_rate']*100:.1f}%")
with k5:
    st.metric("📊 Trades",    stats["trades"])
with k6:
    st.metric("💸 Fees Paid", f"${stats['fees']:.4f}")

st.divider()

# ─── Charts ───────────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    st.subheader("📈 Cumulative P&L")
    closed = _q("SELECT timestamp, pnl FROM trades WHERE status='CLOSED' ORDER BY timestamp")
    if closed:
        df = pd.DataFrame(closed)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["cum_pnl"] = df["pnl"].cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["cum_pnl"],
            mode="lines+markers",
            line=dict(color="#00d4ff", width=2),
            fill="tozeroy", fillcolor="rgba(0,212,255,0.1)",
            name="Cumulative P&L",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.2)")
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#7eb8f7"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickprefix="$"),
            margin=dict(l=0,r=0,t=10,b=0), height=280,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("P&L chart will appear after the first closed trade.")

with col2:
    st.subheader("🎯 Signal Types")
    sigs = get_recent_signals(100)
    if sigs:
        df_s = pd.DataFrame(sigs)
        counts = df_s["direction"].value_counts().reset_index()
        counts.columns = ["Signal", "Count"]
        COLOR_MAP = {
            "STRONG_BUY_YES": "#00ff88", "BUY_YES": "#00cc66",
            "STRONG_BUY_NO":  "#ff4444", "BUY_NO":  "#cc2222",
            "SHOCK_TRADE":    "#ffaa00", "NO_TRADE": "#445566",
        }
        fig2 = px.pie(counts, names="Signal", values="Count",
                      color="Signal", color_discrete_map=COLOR_MAP, hole=0.45)
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#7eb8f7"),
            legend=dict(font=dict(color="#7eb8f7")),
            margin=dict(l=10,r=10,t=10,b=10), height=280,
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Signal chart will appear after the first 10-minute scan cycle.")

st.divider()

# ─── Open Positions ───────────────────────────────────────────────────────────
st.subheader(f"📂 Open Positions ({len(open_trades)})")
if open_trades:
    df_op = pd.DataFrame(open_trades)
    cols  = [c for c in ["timestamp","market_question","direction","entry_price","size_usdc","category","status"] if c in df_op.columns]
    df_op["entry_price"] = df_op["entry_price"].map(lambda x: f"{float(x):.4f}")
    df_op["size_usdc"]   = df_op["size_usdc"].map(lambda x: f"${float(x):.2f}")
    st.dataframe(df_op[cols].rename(columns={
        "timestamp":"Opened","market_question":"Market","direction":"Dir",
        "entry_price":"Entry","size_usdc":"Size","category":"Category","status":"Status"
    }), use_container_width=True, hide_index=True)
else:
    st.info("No open positions. The bot places trades when edge ≥ 7% after fees.")

st.divider()

# ─── Recent Signals ───────────────────────────────────────────────────────────
st.subheader("🎯 Recent Signals (last 15)")
sigs15 = get_recent_signals(15)
if sigs15:
    df_sg = pd.DataFrame(sigs15)
    cols  = [c for c in ["timestamp","market_question","direction","edge","confidence","ai_probability","market_price","acted_on"] if c in df_sg.columns]
    df_sg["edge"]           = df_sg["edge"].map(lambda x: f"{float(x):+.1f}%")
    df_sg["ai_probability"] = df_sg["ai_probability"].map(lambda x: f"{float(x):.1f}%")
    df_sg["market_price"]   = df_sg["market_price"].map(lambda x: f"{float(x):.1f}%")
    df_sg["acted_on"]       = df_sg["acted_on"].map(lambda x: "✅ Traded" if x else "⏭ Skip")
    st.dataframe(df_sg[cols].rename(columns={
        "timestamp":"Time","market_question":"Market","direction":"Signal",
        "edge":"Edge","confidence":"Conf","ai_probability":"AI Prob",
        "market_price":"Mkt Price","acted_on":"Action"
    }), use_container_width=True, hide_index=True)
else:
    st.info("Signals appear here after the first scan cycle (runs every 10 min).")

st.divider()

# ─── Trade History ────────────────────────────────────────────────────────────
st.subheader("📜 Trade History")
trades = get_recent_trades(20)
if trades:
    df_tr = pd.DataFrame(trades)
    cols  = [c for c in ["timestamp","market_question","direction","entry_price","exit_price","size_usdc","pnl","fee_paid","status"] if c in df_tr.columns]
    df_tr["entry_price"] = df_tr["entry_price"].map(lambda x: f"{float(x):.4f}" if x else "—")
    df_tr["exit_price"]  = df_tr["exit_price"].map(lambda x: f"{float(x):.4f}" if x else "—")
    df_tr["size_usdc"]   = df_tr["size_usdc"].map(lambda x: f"${float(x):.2f}" if x else "—")
    df_tr["pnl"]         = df_tr["pnl"].map(lambda x: f"${float(x):+.4f}" if x else "Open")
    df_tr["fee_paid"]    = df_tr["fee_paid"].map(lambda x: f"${float(x):.4f}" if x else "—")
    st.dataframe(df_tr[cols].rename(columns={
        "timestamp":"Time","market_question":"Market","direction":"Dir",
        "entry_price":"Entry","exit_price":"Exit","size_usdc":"Size",
        "pnl":"P&L","fee_paid":"Fee","status":"Status"
    }), use_container_width=True, hide_index=True)
else:
    st.info("Trade history will appear here once trades are placed.")

st.divider()

# ─── Live Markets Preview ─────────────────────────────────────────────────────
st.subheader("🌐 Live Polymarket Scan (last known markets)")
mkt_sigs = _q("SELECT DISTINCT market_question, market_id, MAX(timestamp) as latest, ai_probability, market_price, edge, confidence FROM signals GROUP BY market_id ORDER BY latest DESC LIMIT 15")
if mkt_sigs:
    df_mkt = pd.DataFrame(mkt_sigs)
    df_mkt["ai_probability"] = df_mkt["ai_probability"].map(lambda x: f"{float(x):.1f}%")
    df_mkt["market_price"]   = df_mkt["market_price"].map(lambda x: f"{float(x):.1f}%")
    df_mkt["edge"]           = df_mkt["edge"].map(lambda x: f"{float(x):+.1f}%")
    st.dataframe(df_mkt[["market_question","ai_probability","market_price","edge","confidence","latest"]].rename(columns={
        "market_question":"Market","ai_probability":"AI Prob",
        "market_price":"Mkt Price","edge":"Edge","confidence":"Conf","latest":"Last Scanned"
    }), use_container_width=True, hide_index=True)
else:
    st.info("Markets scanned by the bot will appear here.")

# ─── Footer & Auto-refresh ────────────────────────────────────────────────────
st.caption("PolyEdge AI © 2025 — Educational purposes only. US persons cannot use Polymarket.")

if auto:
    time.sleep(refresh)
    st.rerun()
