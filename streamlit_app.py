"""
PolyEdge AI — Streamlit Dashboard v2
Vibrant dark trading dashboard. Reads from SQLite DB.
Deploy free at streamlit.io/cloud
"""
import os
import sqlite3
import time
from datetime import datetime, timezone, date

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dotenv import load_dotenv

load_dotenv()

# ── Config (no heavy bot imports) ─────────────────────────────────────────────
DB_PATH          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "polyedge", "polyedge.db")
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "100.0"))
DRY_RUN          = os.getenv("DRY_RUN", "true").lower() == "true"
GROQ_MODEL       = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_OPEN_POS     = int(os.getenv("MAX_OPEN_POSITIONS", "4"))
MIN_EDGE         = float(os.getenv("MIN_EDGE_AFTER_FEE", "7.0"))

# ── Page Setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PolyEdge AI Trading",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap');

/* ── Base ── */
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp {
    background: linear-gradient(135deg, #060912 0%, #0b1120 50%, #07101e 100%);
    color: #e8edf5;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0b1120 0%, #070d1a 100%) !important;
    border-right: 1px solid rgba(0, 200, 255, 0.15) !important;
}
section[data-testid="stSidebar"] * { color: #c8d8f0 !important; }
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stCheckbox label { color: #8ba8cc !important; }

/* ── Headings ── */
h1 { color: #ffffff !important; font-weight: 900 !important; font-size: 2.2rem !important; }
h2 { color: #ffffff !important; font-weight: 700 !important; font-size: 1.35rem !important; }
h3 { color: #e0eaff !important; font-weight: 600 !important; }
p, span, label { color: #c0d0e8 !important; }

/* ── Metric Cards ── */
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, rgba(0,200,255,0.07) 0%, rgba(0,80,200,0.05) 100%) !important;
    border: 1px solid rgba(0, 200, 255, 0.18) !important;
    border-radius: 14px !important;
    padding: 18px 22px !important;
    transition: border-color 0.2s ease;
}
div[data-testid="metric-container"]:hover {
    border-color: rgba(0, 200, 255, 0.4) !important;
}
div[data-testid="metric-container"] label {
    color: #7a99c0 !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}
div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #ffffff !important;
    font-size: 1.9rem !important;
    font-weight: 800 !important;
}
div[data-testid="metric-container"] [data-testid="stMetricDelta"] {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
}

/* ── Divider ── */
hr { border-color: rgba(0, 200, 255, 0.1) !important; margin: 1rem 0 !important; }

/* ── Info/Warning boxes ── */
div[data-testid="stAlert"] {
    background: rgba(0,200,255,0.06) !important;
    border: 1px solid rgba(0,200,255,0.2) !important;
    border-radius: 10px !important;
    color: #b0d0f0 !important;
}

/* ── Tables ── */
div[data-testid="stDataFrame"] {
    border: 1px solid rgba(0,200,255,0.12) !important;
    border-radius: 10px !important;
    overflow: hidden;
}
.stDataFrame thead tr th {
    background: rgba(0,200,255,0.1) !important;
    color: #00c8ff !important;
    font-weight: 700 !important;
    font-size: 0.78rem !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid rgba(0,200,255,0.2) !important;
}

/* ── Sidebar badge ── */
.mode-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    margin-bottom: 8px;
}
.mode-dry { background: rgba(255,170,0,0.15); color: #ffaa00; border: 1px solid rgba(255,170,0,0.3); }
.mode-live { background: rgba(255,60,60,0.15); color: #ff4444; border: 1px solid rgba(255,60,60,0.3); }

/* ── Section headers ── */
.section-header {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 0 6px 0;
    border-bottom: 1px solid rgba(0,200,255,0.15);
    margin-bottom: 14px;
}
.section-header .icon { font-size: 1.4rem; }
.section-header .title {
    font-size: 1.1rem; font-weight: 700;
    color: #ffffff !important;
    letter-spacing: 0.01em;
}

/* ── Signal Badges ── */
.sig-badge {
    display: inline-block; padding: 3px 10px; border-radius: 12px;
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.03em;
}
.sig-strong-yes { background: rgba(0,255,120,0.15); color: #00ff78; border: 1px solid rgba(0,255,120,0.35); }
.sig-yes        { background: rgba(0,200,100,0.12); color: #00cc66; border: 1px solid rgba(0,200,100,0.30); }
.sig-strong-no  { background: rgba(255,60,60,0.15);  color: #ff4444; border: 1px solid rgba(255,60,60,0.35); }
.sig-no         { background: rgba(220,80,80,0.12);  color: #ff7777; border: 1px solid rgba(220,80,80,0.30); }
.sig-shock      { background: rgba(255,160,0,0.15);  color: #ffaa00; border: 1px solid rgba(255,160,0,0.35); }
.sig-none       { background: rgba(80,100,130,0.15); color: #7090b0; border: 1px solid rgba(80,100,130,0.30); }

/* ── Status Dots ── */
.dot-green { display:inline-block; width:8px; height:8px; border-radius:50%; background:#00ff78; box-shadow:0 0 6px #00ff78; margin-right:6px; }
.dot-red   { display:inline-block; width:8px; height:8px; border-radius:50%; background:#ff4444; box-shadow:0 0 6px #ff4444; margin-right:6px; }
.dot-yellow{ display:inline-block; width:8px; height:8px; border-radius:50%; background:#ffaa00; box-shadow:0 0 6px #ffaa00; margin-right:6px; }

/* ── KPI row ── */
.kpi-row { margin-bottom: 24px; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-thumb { background: rgba(0,200,255,0.25); border-radius: 3px; }
::-webkit-scrollbar-track { background: transparent; }
</style>
""", unsafe_allow_html=True)


# ── DB Helpers (raw SQLite, no bot imports) ────────────────────────────────────
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

@st.cache_data(ttl=10)
def get_open_trades():
    return _q("SELECT * FROM trades WHERE status='OPEN' ORDER BY timestamp DESC")

@st.cache_data(ttl=10)
def get_recent_trades(n=25):
    return _q("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (n,))

@st.cache_data(ttl=10)
def get_recent_signals(n=25):
    return _q("SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (n,))

@st.cache_data(ttl=20)
def get_daily_pnl():
    today = date.today().isoformat()
    rows = _q("SELECT COALESCE(SUM(pnl),0) as t FROM trades WHERE date(timestamp)=? AND status='CLOSED'", (today,))
    return float(rows[0]["t"]) if rows else 0.0

@st.cache_data(ttl=20)
def get_total_pnl():
    rows = _q("SELECT COALESCE(SUM(pnl),0) as t FROM trades WHERE status='CLOSED'")
    return float(rows[0]["t"]) if rows else 0.0

@st.cache_data(ttl=20)
def get_stats():
    rows = _q("""SELECT COUNT(*) as n,
                        SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as w,
                        COALESCE(SUM(fee_paid),0) as f
                 FROM trades WHERE status='CLOSED'""")
    if rows:
        n = rows[0]["n"] or 0
        w = rows[0]["w"] or 0
        f = rows[0]["f"] or 0.0
        return {"trades": n, "wins": w, "win_rate": (w/n if n else 0), "fees": f}
    return {"trades": 0, "wins": 0, "win_rate": 0.0, "fees": 0.0}

@st.cache_data(ttl=60)
def get_closed_trades_for_chart():
    return _q("SELECT timestamp, pnl FROM trades WHERE status='CLOSED' ORDER BY timestamp")

@st.cache_data(ttl=15)
def get_market_scan():
    return _q("""SELECT DISTINCT market_question, market_id, MAX(timestamp) as latest,
                        ai_probability, market_price, edge, confidence
                 FROM signals GROUP BY market_id ORDER BY latest DESC LIMIT 15""")

@st.cache_data(ttl=30)
def get_last_scan_time():
    rows = _q("SELECT MAX(timestamp) as t FROM signals")
    return rows[0]["t"] if rows and rows[0]["t"] else None

def _sig_badge(sig_type: str) -> str:
    mapping = {
        "STRONG_BUY_YES": ("sig-strong-yes", "⬆⬆ STRONG BUY YES"),
        "BUY_YES":        ("sig-yes",        "⬆ BUY YES"),
        "STRONG_BUY_NO":  ("sig-strong-no",  "⬇⬇ STRONG SELL"),
        "BUY_NO":         ("sig-no",         "⬇ BUY NO"),
        "SHOCK_TRADE":    ("sig-shock",       "⚡ SHOCK"),
        "NO_TRADE":       ("sig-none",        "— SKIP"),
    }
    cls, label = mapping.get(sig_type, ("sig-none", sig_type))
    return f'<span class="sig-badge {cls}">{label}</span>'

def _pnl_color(v) -> str:
    try:
        f = float(v)
        color = "#00ff78" if f > 0 else ("#ff4444" if f < 0 else "#8899aa")
        return f'<span style="color:{color};font-weight:700">${f:+.4f}</span>'
    except Exception:
        return str(v)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ PolyEdge AI")
    st.markdown("*Autonomous Prediction Market Bot*")
    st.divider()

    mode_cls   = "mode-dry" if DRY_RUN else "mode-live"
    mode_label = "🟡 DRY RUN MODE" if DRY_RUN else "🔴 LIVE TRADING"
    st.markdown(f'<div class="mode-badge {mode_cls}">{mode_label}</div>', unsafe_allow_html=True)
    st.markdown(f"**Model:** `{GROQ_MODEL}`")
    st.markdown(f"**Min Edge:** `{MIN_EDGE}%`")
    st.markdown(f"**Max Positions:** `{MAX_OPEN_POS}`")
    st.markdown(f"**Capital:** `${STARTING_CAPITAL:.2f}`")
    st.divider()

    if db_ready():
        last_scan = get_last_scan_time()
        if last_scan:
            st.markdown(f'<span class="dot-green"></span>**Bot Active**', unsafe_allow_html=True)
            st.caption(f"Last scan: {last_scan[:19].replace('T',' ')} UTC")
        else:
            st.markdown(f'<span class="dot-yellow"></span>**DB Ready, No Scans Yet**', unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="dot-red"></span>**Bot Offline**', unsafe_allow_html=True)
        st.warning("Start `main.py` or wait for GitHub Actions to trigger the first cycle.", icon="⚠️")

    st.divider()
    refresh = st.selectbox("Auto-refresh every", [10, 20, 30, 60], index=1,
                           format_func=lambda x: f"{x} seconds")
    auto = st.checkbox("Enable auto-refresh", value=True)
    st.divider()
    st.caption("⚠️ US persons cannot use Polymarket. Educational tool. Not financial advice.")


# ── Header ────────────────────────────────────────────────────────────────────
col_t, col_time = st.columns([5, 1])
with col_t:
    st.markdown("# ⚡ PolyEdge AI")
    st.markdown('<p style="color:#7090b0;margin-top:-12px;font-size:0.9rem">Autonomous Prediction Market Intelligence System</p>', unsafe_allow_html=True)
with col_time:
    now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S")
    st.markdown(f'<div style="text-align:right;padding-top:16px"><span style="background:rgba(0,200,255,0.1);border:1px solid rgba(0,200,255,0.25);border-radius:8px;padding:6px 12px;font-size:0.82rem;color:#00c8ff;font-weight:600">🕐 {now_utc} UTC</span></div>', unsafe_allow_html=True)

st.divider()

# ── DB Not Ready Banner ───────────────────────────────────────────────────────
if not db_ready():
    st.markdown("""
    <div style="background:linear-gradient(135deg,rgba(255,140,0,0.1),rgba(255,80,0,0.05));
                border:1px solid rgba(255,140,0,0.3);border-radius:14px;padding:24px 28px">
        <h3 style="color:#ffaa00;margin:0 0 12px 0">🚀 Bot Not Running Yet</h3>
        <p style="color:#c0a060;margin:0 0 16px 0">Start the bot to begin collecting data. The dashboard will auto-populate within 2 minutes.</p>
        <p style="color:#8090a0;font-size:0.85rem;margin:0"><b>Option A (local):</b> <code>cd polyedge && python main.py</code></p>
        <p style="color:#8090a0;font-size:0.85rem;margin:4px 0 0 0"><b>Option B (cloud):</b> Push to GitHub — Actions runs it automatically every 10 min</p>
    </div>
    """, unsafe_allow_html=True)
    if auto:
        time.sleep(refresh)
        st.rerun()
    st.stop()


# ── KPI Row ───────────────────────────────────────────────────────────────────
open_trades = get_open_trades()
daily_pnl   = get_daily_pnl()
total_pnl   = get_total_pnl()
stats       = get_stats()
current_cap = STARTING_CAPITAL + total_pnl
cap_delta   = total_pnl / STARTING_CAPITAL * 100

k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    st.metric("💰 Portfolio Value", f"${current_cap:.2f}", delta=f"{total_pnl:+.2f} total")
with k2:
    st.metric("📈 Today P&L", f"${daily_pnl:+.4f}")
with k3:
    st.metric("📂 Open Positions", f"{len(open_trades)} / {MAX_OPEN_POS}")
with k4:
    win_pct = f"{stats['win_rate']*100:.1f}%" if stats["trades"] > 0 else "—"
    st.metric("🏆 Win Rate", win_pct, delta=f"{stats['wins']} wins" if stats["trades"] > 0 else None)
with k5:
    st.metric("📊 Trades Closed", stats["trades"])
with k6:
    st.metric("💸 Fees Paid", f"${stats['fees']:.4f}")

st.divider()


# ── Charts Row ────────────────────────────────────────────────────────────────
chart_col1, chart_col2 = st.columns([3, 2])

with chart_col1:
    st.markdown('<div class="section-header"><span class="icon">📈</span><span class="title">Cumulative P&L</span></div>', unsafe_allow_html=True)
    closed = get_closed_trades_for_chart()
    if closed:
        df = pd.DataFrame(closed)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["cum_pnl"]   = df["pnl"].cumsum()
        final_color = "#00ff78" if df["cum_pnl"].iloc[-1] >= 0 else "#ff4444"
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["timestamp"], y=df["cum_pnl"],
            mode="lines+markers",
            line=dict(color=final_color, width=2.5),
            marker=dict(size=5, color=final_color, line=dict(color="#060912", width=1)),
            fill="tozeroy",
            fillcolor=f"rgba({','.join(str(int(final_color.lstrip('#')[i:i+2],16)) for i in (0,2,4))},0.08)",
            name="P&L",
            hovertemplate="<b>%{x|%b %d %H:%M}</b><br>P&L: $%{y:+.4f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.15)", line_width=1)
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8099bb", family="Inter"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.04)", showgrid=True, tickfont=dict(size=11)),
            yaxis=dict(gridcolor="rgba(255,255,255,0.04)", showgrid=True, tickprefix="$", tickfont=dict(size=11)),
            margin=dict(l=0, r=0, t=8, b=0), height=260,
            showlegend=False, hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.markdown('<div style="height:200px;display:flex;align-items:center;justify-content:center;color:#445566;font-size:0.9rem">📊 P&L chart appears after the first closed trade</div>', unsafe_allow_html=True)

with chart_col2:
    st.markdown('<div class="section-header"><span class="icon">🎯</span><span class="title">Signal Distribution</span></div>', unsafe_allow_html=True)
    sigs_all = get_recent_signals(150)
    if sigs_all:
        df_s    = pd.DataFrame(sigs_all)
        counts  = df_s["direction"].value_counts().reset_index()
        counts.columns = ["Signal", "Count"]
        SIGNAL_COLORS = {
            "STRONG_BUY_YES": "#00ff78", "BUY_YES": "#00cc55",
            "STRONG_BUY_NO":  "#ff4444", "BUY_NO":  "#ff7777",
            "SHOCK_TRADE":    "#ffaa00", "NO_TRADE": "#2a3548",
        }
        colors = [SIGNAL_COLORS.get(s, "#445566") for s in counts["Signal"]]
        fig2 = go.Figure(go.Pie(
            labels=counts["Signal"], values=counts["Count"],
            hole=0.52, marker=dict(colors=colors, line=dict(color="#060912", width=2)),
            textinfo="label+percent", textfont=dict(size=11, color="#e0eaff"),
            hovertemplate="<b>%{label}</b><br>Count: %{value}<br>Share: %{percent}<extra></extra>",
        ))
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#8099bb", family="Inter"),
            legend=dict(font=dict(color="#c0d0e8", size=11), bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=0, r=0, t=8, b=0), height=260, showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.markdown('<div style="height:200px;display:flex;align-items:center;justify-content:center;color:#445566;font-size:0.9rem">🎯 Signals appear after first scan cycle</div>', unsafe_allow_html=True)

st.divider()


# ── Open Positions ────────────────────────────────────────────────────────────
pos_count = len(open_trades)
pos_color = "#00ff78" if pos_count == 0 else ("#ffaa00" if pos_count < MAX_OPEN_POS else "#ff4444")
st.markdown(f'<div class="section-header"><span class="icon">📂</span><span class="title">Open Positions <span style="color:{pos_color}">({pos_count} / {MAX_OPEN_POS})</span></span></div>', unsafe_allow_html=True)

if open_trades:
    for trade in open_trades:
        entry = float(trade.get("entry_price") or 0)
        size  = float(trade.get("size_usdc") or 0)
        dir_  = trade.get("direction", "")
        badge = _sig_badge(dir_)
        cat   = trade.get("category","Other")
        opened = str(trade.get("timestamp",""))[:16].replace("T"," ")

        with st.container():
            c1, c2, c3, c4, c5 = st.columns([4, 1, 1, 1, 1])
            with c1:
                st.markdown(f'<p style="color:#e8f0ff;font-weight:600;margin:0;font-size:0.92rem">{trade.get("market_question","")[:80]}</p>', unsafe_allow_html=True)
            with c2:
                st.markdown(badge, unsafe_allow_html=True)
            with c3:
                st.markdown(f'<p style="color:#00c8ff;font-weight:700;margin:0">Entry: {entry:.4f}</p>', unsafe_allow_html=True)
            with c4:
                st.markdown(f'<p style="color:#ffaa00;font-weight:700;margin:0">${size:.2f}</p>', unsafe_allow_html=True)
            with c5:
                st.markdown(f'<p style="color:#5577aa;font-size:0.8rem;margin:0">{opened}</p>', unsafe_allow_html=True)
        st.markdown('<hr style="margin:6px 0;border-color:rgba(0,200,255,0.06)">', unsafe_allow_html=True)
else:
    st.markdown('<div style="padding:20px;text-align:center;color:#3a5070;font-size:0.9rem;border:1px dashed rgba(0,200,255,0.1);border-radius:10px">No open positions. Bot places trades when edge ≥ 7% after 2% Polymarket fee.</div>', unsafe_allow_html=True)

st.divider()


# ── Live Market Scan Table ────────────────────────────────────────────────────
st.markdown('<div class="section-header"><span class="icon">🌐</span><span class="title">Last Market Scan — AI vs Market Price</span></div>', unsafe_allow_html=True)
mkt_scan = get_market_scan()
if mkt_scan:
    df_mkt = pd.DataFrame(mkt_scan)

    def edge_style(edge_val):
        try:
            e = float(edge_val)
            if e >= 8:  return f'<span style="color:#00ff78;font-weight:800">{e:+.1f}%</span>'
            if e >= 5:  return f'<span style="color:#00cc55;font-weight:700">{e:+.1f}%</span>'
            if e <= -5: return f'<span style="color:#ff7777;font-weight:700">{e:+.1f}%</span>'
            return f'<span style="color:#6688aa">{e:+.1f}%</span>'
        except Exception:
            return str(edge_val)

    def conf_badge(conf):
        colors = {"HIGH":"#00ff78","MEDIUM":"#ffaa00","LOW":"#ff7777"}
        c = colors.get(str(conf).upper(), "#667788")
        return f'<span style="color:{c};font-weight:700;font-size:0.8rem">{conf}</span>'

    # Build HTML rows
    table_html = """
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.87rem">
    <thead>
      <tr style="border-bottom:1px solid rgba(0,200,255,0.2)">
        <th style="text-align:left;padding:10px 12px;color:#00c8ff;font-weight:700;text-transform:uppercase;font-size:0.75rem;letter-spacing:0.05em">Market Question</th>
        <th style="text-align:center;padding:10px 12px;color:#00c8ff;font-weight:700;text-transform:uppercase;font-size:0.75rem;letter-spacing:0.05em">🤖 AI Prob</th>
        <th style="text-align:center;padding:10px 12px;color:#00c8ff;font-weight:700;text-transform:uppercase;font-size:0.75rem;letter-spacing:0.05em">📊 Mkt Price</th>
        <th style="text-align:center;padding:10px 12px;color:#00c8ff;font-weight:700;text-transform:uppercase;font-size:0.75rem;letter-spacing:0.05em">↔ Edge</th>
        <th style="text-align:center;padding:10px 12px;color:#00c8ff;font-weight:700;text-transform:uppercase;font-size:0.75rem;letter-spacing:0.05em">Confidence</th>
        <th style="text-align:right;padding:10px 12px;color:#00c8ff;font-weight:700;text-transform:uppercase;font-size:0.75rem;letter-spacing:0.05em">Scanned</th>
      </tr>
    </thead>
    <tbody>"""

    for i, row in df_mkt.iterrows():
        bg = "rgba(0,200,255,0.03)" if i % 2 == 0 else "rgba(0,0,0,0)"
        ai_p  = f"{float(row.get('ai_probability',0)):.1f}%"
        mkt_p = f"{float(row.get('market_price',0)):.1f}%"
        edge  = edge_style(row.get("edge", 0))
        conf  = conf_badge(row.get("confidence","?"))
        ts    = str(row.get("latest",""))[:16].replace("T"," ")
        q     = str(row.get("market_question",""))[:70]
        table_html += f"""
        <tr style="background:{bg};border-bottom:1px solid rgba(255,255,255,0.04)">
          <td style="padding:9px 12px;color:#d0e0f8">{q}</td>
          <td style="text-align:center;padding:9px 12px;color:#e0eaff;font-weight:600">{ai_p}</td>
          <td style="text-align:center;padding:9px 12px;color:#c0d0e8">{mkt_p}</td>
          <td style="text-align:center;padding:9px 12px">{edge}</td>
          <td style="text-align:center;padding:9px 12px">{conf}</td>
          <td style="text-align:right;padding:9px 12px;color:#4a6080;font-size:0.8rem">{ts}</td>
        </tr>"""

    table_html += "</tbody></table></div>"
    st.markdown(table_html, unsafe_allow_html=True)
else:
    st.markdown('<div style="padding:20px;text-align:center;color:#3a5070;font-size:0.9rem;border:1px dashed rgba(0,200,255,0.1);border-radius:10px">Market scan data appears after the first 10-minute cycle.</div>', unsafe_allow_html=True)

st.divider()


# ── Recent Signals ────────────────────────────────────────────────────────────
st.markdown('<div class="section-header"><span class="icon">🎯</span><span class="title">Recent Signals (last 15)</span></div>', unsafe_allow_html=True)

sigs15 = get_recent_signals(15)
if sigs15:
    sig_table = """
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.86rem">
    <thead>
      <tr style="border-bottom:1px solid rgba(0,200,255,0.18)">
        <th style="text-align:left;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Time</th>
        <th style="text-align:left;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Market</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Signal</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">AI Prob</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Mkt</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Edge</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Conf</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Traded?</th>
      </tr>
    </thead><tbody>"""

    for i, sig in enumerate(sigs15):
        bg    = "rgba(0,200,255,0.03)" if i % 2 == 0 else "rgba(0,0,0,0)"
        ts    = str(sig.get("timestamp",""))[:16].replace("T"," ")
        q     = str(sig.get("market_question",""))[:52]
        badge = _sig_badge(str(sig.get("direction","")))
        ai_p  = f"{float(sig.get('ai_probability',0)):.1f}%"
        mkt   = f"{float(sig.get('market_price',0)):.1f}%"
        edge  = float(sig.get("edge",0))
        ecol  = "#00ff78" if edge >= 7 else ("#ffaa00" if edge >= 5 else "#5577aa")
        estr  = f'<span style="color:{ecol};font-weight:700">{edge:+.1f}%</span>'
        conf  = str(sig.get("confidence","?"))
        ccol  = {"HIGH":"#00ff78","MEDIUM":"#ffaa00","LOW":"#ff7777"}.get(conf.upper(),"#667788")
        cstr  = f'<span style="color:{ccol};font-weight:600">{conf}</span>'
        acted = sig.get("acted_on", 0)
        astr  = '<span style="color:#00ff78">✅ Traded</span>' if acted else '<span style="color:#445566">⏭ Skip</span>'

        sig_table += f"""
        <tr style="background:{bg};border-bottom:1px solid rgba(255,255,255,0.03)">
          <td style="padding:8px 12px;color:#4a6080;font-size:0.8rem;white-space:nowrap">{ts}</td>
          <td style="padding:8px 12px;color:#c8d8f0">{q}</td>
          <td style="padding:8px 12px;text-align:center">{badge}</td>
          <td style="padding:8px 12px;text-align:center;color:#d0e0f8;font-weight:600">{ai_p}</td>
          <td style="padding:8px 12px;text-align:center;color:#8090aa">{mkt}</td>
          <td style="padding:8px 12px;text-align:center">{estr}</td>
          <td style="padding:8px 12px;text-align:center">{cstr}</td>
          <td style="padding:8px 12px;text-align:center">{astr}</td>
        </tr>"""

    sig_table += "</tbody></table></div>"
    st.markdown(sig_table, unsafe_allow_html=True)
else:
    st.markdown('<div style="padding:20px;text-align:center;color:#3a5070;font-size:0.9rem;border:1px dashed rgba(0,200,255,0.1);border-radius:10px">Signals appear after the first scan cycle completes.</div>', unsafe_allow_html=True)

st.divider()


# ── Trade History ─────────────────────────────────────────────────────────────
st.markdown('<div class="section-header"><span class="icon">📜</span><span class="title">Trade History (last 20)</span></div>', unsafe_allow_html=True)
trades = get_recent_trades(20)
if trades:
    trade_table = """
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.86rem">
    <thead>
      <tr style="border-bottom:1px solid rgba(0,200,255,0.18)">
        <th style="text-align:left;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Time</th>
        <th style="text-align:left;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Market</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Dir</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Entry</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Exit</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Size</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">P&L</th>
        <th style="text-align:center;padding:9px 12px;color:#00c8ff;font-size:0.73rem;text-transform:uppercase;letter-spacing:0.05em">Status</th>
      </tr>
    </thead><tbody>"""

    for i, t in enumerate(trades):
        bg     = "rgba(0,200,255,0.03)" if i % 2 == 0 else "rgba(0,0,0,0)"
        ts     = str(t.get("timestamp",""))[:16].replace("T"," ")
        q      = str(t.get("market_question",""))[:52]
        badge  = _sig_badge(str(t.get("direction","")))
        entry  = f'{float(t.get("entry_price") or 0):.4f}'
        exit_p = f'{float(t.get("exit_price") or 0):.4f}' if t.get("exit_price") else "Open"
        size   = f'${float(t.get("size_usdc") or 0):.2f}'
        pnl    = t.get("pnl")
        pnl_h  = _pnl_color(pnl) if pnl is not None else '<span style="color:#445566">—</span>'
        status = str(t.get("status","?"))
        scol   = {"OPEN":"#ffaa00","CLOSED":"#00ff78","CANCELLED":"#ff7777"}.get(status,"#667788")
        sstr   = f'<span style="color:{scol};font-weight:700;font-size:0.8rem">{status}</span>'

        trade_table += f"""
        <tr style="background:{bg};border-bottom:1px solid rgba(255,255,255,0.03)">
          <td style="padding:8px 12px;color:#4a6080;font-size:0.8rem;white-space:nowrap">{ts}</td>
          <td style="padding:8px 12px;color:#c8d8f0">{q}</td>
          <td style="padding:8px 12px;text-align:center">{badge}</td>
          <td style="padding:8px 12px;text-align:center;color:#00c8ff;font-weight:600">{entry}</td>
          <td style="padding:8px 12px;text-align:center;color:#8090aa">{exit_p}</td>
          <td style="padding:8px 12px;text-align:center;color:#ffaa00;font-weight:600">{size}</td>
          <td style="padding:8px 12px;text-align:center">{pnl_h}</td>
          <td style="padding:8px 12px;text-align:center">{sstr}</td>
        </tr>"""

    trade_table += "</tbody></table></div>"
    st.markdown(trade_table, unsafe_allow_html=True)
else:
    st.markdown('<div style="padding:20px;text-align:center;color:#3a5070;font-size:0.9rem;border:1px dashed rgba(0,200,255,0.1);border-radius:10px">Trade history will appear here once trades are executed.</div>', unsafe_allow_html=True)

st.divider()

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;padding:12px 0;color:#2a3a50;font-size:0.78rem">
    PolyEdge AI v2 &nbsp;·&nbsp; Educational purposes only &nbsp;·&nbsp; US persons cannot use Polymarket
</div>
""", unsafe_allow_html=True)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto:
    time.sleep(refresh)
    st.rerun()
