# PolyEdge AI — Simple Overview
**What this bot is and how it works (plain English)**

---

## What Does It Do?

PolyEdge AI is an **autonomous trading bot** for [Polymarket](https://polymarket.com) — a website where you bet real money on yes/no questions like:

- *"Will the Fed cut interest rates in May?"*
- *"Will Bitcoin reach $100k by June?"*
- *"Will the Iranian regime fall by April 30?"*

The bot finds markets where **the crowd is WRONG** and bets against them automatically. It does this 24/7 while you sleep.

---

## How It Makes Money (The Core Idea)

If Polymarket says there's a **10% chance** of something, but our AI thinks it's actually **25%**, that's a **+15% edge**. We buy that contract cheaply, and if the AI is right, we profit.

```
Market says:  10%  (price = $0.10)
AI thinks:    25%  (true probability)
Edge:        +15%  ← we BUY this
```

---

## The 5 Steps Every 10 Minutes

```
1. SCAN         → Find the 15 best Polymarket markets (high volume, active)
                   Source: Polymarket Gamma API (free, no auth needed)

2. NEWS         → Pull headlines about each market topic
                   Sources: Google News, HackerNews, BBC, Reuters, AP, 
                            Wikipedia, NPR, Guardian, Politico, CoinDesk

3. AI ANALYSE   → Send question + news to Groq AI (llama-3.3-70b)
                   AI returns: probability estimate + reasoning

4. SIGNAL       → Compare AI probability vs market price
                   If edge > 7% → generate a trade signal
                   Signals: BUY_YES | BUY_NO | STRONG_BUY_YES | STRONG_BUY_NO

5. TRADE        → Place a limit order on the CLOB
                   DRY_RUN=true → paper trade only (no real money)
                   DRY_RUN=false → real USDC order
```

---

## Files Explained

```
polymarket/
│
├── .env                    ← Your secrets (API keys, private key)
│                             NEVER commit this to GitHub
│
├── requirements.txt        ← Python packages needed to run
│
├── streamlit_app.py        ← Web dashboard at http://localhost:8501
│                             Shows: signals, trades, P&L, charts
│
└── polyedge/               ← The brain of the bot
    │
    ├── main.py             ← ENTRY POINT — run this to start the bot
    │                         Runs all 5 loops on a timer using APScheduler
    │
    ├── config.py           ← ALL settings in one place
    │                         Edit this to change thresholds, capital, etc.
    │
    ├── market_scanner.py   ← Step 1: fetches markets from Gamma API
    │                         Filters by volume, liquidity, expiry
    │
    ├── news_engine.py      ← Step 2: pulls news from 10+ free sources
    │                         Also detects breaking news "shocks"
    │
    ├── ai_analyst.py       ← Step 3: sends data to Groq AI
    │                         Returns probability estimate with reasoning
    │
    ├── signal_detector.py  ← Step 4: compares AI prob vs market price
    │                         Generates typed signals (BUY/SELL/HOLD)
    │
    ├── trade_executor.py   ← Step 5: places orders via Polymarket CLOB API
    │                         Handles dry-run vs live mode
    │
    ├── risk_manager.py     ← Protects your capital
    │                         Kelly Criterion sizing + stop-loss logic
    │
    ├── database.py         ← SQLite database (polyedge.db)
    │                         Logs all signals, trades, P&L
    │
    ├── dashboard.py        ← Terminal dashboard (Rich library)
    │                         Shows live stats in the console
    │
    └── notifier.py         ← Windows toast notifications for trades
```

---

## Key Settings (edit `polyedge/config.py`)

| Setting | Default | What it does |
|---------|---------|-------------|
| `DRY_RUN` | `true` | Paper trade only — no real money |
| `STARTING_CAPITAL` | `$100` | Your starting bankroll |
| `MIN_EDGE_AFTER_FEE` | `7%` | Minimum edge to place a trade |
| `MAX_SINGLE_TRADE_PCT` | `8%` | Max bet size (% of capital) |
| `MAX_OPEN_POSITIONS` | `4` | Max 4 trades at once |
| `STOP_LOSS_PCT` | `50%` | Exit if position loses 50% |
| `TAKE_PROFIT_PROBABILITY` | `85%` | Exit when market reaches 85% |
| `KELLY_FRACTION` | `0.5` | Half-Kelly (conservative sizing) |

---

## How to Run

### Start the Bot (terminal dashboard)
```powershell
cd polyedge
python main.py
```

### Start the Web Dashboard (separate terminal)
```powershell
.\poly\Scripts\Activate.ps1
streamlit run streamlit_app.py
# Then open: http://localhost:8501
```

### Run Both
Open **two PowerShell windows** — one for each command above.

---

## DRY RUN vs LIVE Mode

| | DRY_RUN=true | DRY_RUN=false |
|--|--|--|
| Real money spent | ❌ No | ✅ Yes |
| Trades logged | ✅ Yes (paper) | ✅ Yes (real) |
| CLOB API called | ❌ No | ✅ Yes |
| Safe to test | ✅ Yes | ⚠️ Real money! |

> 💡 **Always run DRY_RUN=true for at least 1 week** before switching to live. Watch the win rate and edge quality first.

---

## Signal Explanation

| Signal | Meaning | Action |
|--------|---------|--------|
| `STRONG_BUY_YES` | Edge ≥ 8%, HIGH confidence, vol > $10k | Buy YES shares |
| `BUY_YES` | Edge ≥ 5%, MEDIUM+ confidence | Buy YES shares (smaller size) |
| `STRONG_BUY_NO` | Edge ≥ 8% on NO side, HIGH confidence | Buy NO shares |
| `BUY_NO` | Edge ≥ 5% on NO side | Buy NO shares |
| `SHOCK_TRADE` | Breaking news shifts probability ≥ 10% | Urgent trade |
| `NO_TRADE` | Edge too small or LOW confidence | Do nothing |

---

## The Money Flow

```
$100 starting capital
     │
     ▼
 Bot places DRY_RUN paper trades
     │
     ├─ Trade 1: Buy YES on Iran ceasefire @ $0.095 → 8% of capital = $8
     ├─ Trade 2: Buy NO on Fed rate cut @ $0.004 → 5% of capital = $5
     └─ ...up to 4 open positions at once
     │
     ▼
 Market resolves:
     ├─ WIN: $1.00 payout (e.g. paid $0.095 → profit = $0.905 per share)
     └─ LOSS: $0.00 payout
```

---

## FAQ

**Q: Is this legal?**  
A: Polymarket is legal for non-US persons. US-based people cannot legally use it. Always check your local laws.

**Q: Can I lose all my money?**  
A: Yes. AI predictions can be wrong. Always start with DRY_RUN=true and only use capital you can afford to lose.

**Q: Why is the GROQ_API_KEY needed?**  
A: It's the free AI service that analyses each market. Without it, the bot cannot generate probability estimates.

**Q: Why did you use HackerNews instead of Reddit?**  
A: Reddit changed their API policies in 2023-2024, making it very hard to create free apps. HackerNews provides similar crowd-sourced news signals with zero registration required.

**Q: How often does the bot trade?**  
A: Scans every 10 minutes. Only trades when edge ≥ 7%. Realistically, 1-5 trades per day depending on market conditions.
