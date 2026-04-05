# ⚡ PolyEdge AI — Autonomous Polymarket Trading System

> **⚠️ DISCLAIMER:** US persons **cannot** legally use Polymarket. This software is for **educational purposes only**. Prediction market trading carries significant financial risk. Always paper-trade for at least 1 week before using real money. The authors are not responsible for financial losses.

---

## What Is This?

PolyEdge AI is a fully autonomous trading bot for [Polymarket](https://polymarket.com) that:

- **Scans** 15+ active markets every 10 minutes via the Gamma API
- **Aggregates real-time news** from Reuters, BBC, AP, Al Jazeera, Google News, Reddit, and Wikipedia
- **Uses Groq AI** (free cloud LLM — `llama-3.3-70b-versatile`) to estimate the _true_ probability of each market outcome
- **Detects mispricings** where the AI's probability differs from the market price by 7%+ after fees
- **Places limit orders** via the Polymarket CLOB API
- **Manages risk** with Kelly Criterion sizing, stop-loss, take-profit, and daily loss limits
- **Runs 24/7** on Windows with ~200MB RAM — no GPU, no local LLM

---

## 📁 File Structure

```
polymarket/
├── polyedge/
│   ├── main.py            # Entry point — APScheduler + terminal dashboard
│   ├── config.py          # All settings and risk parameters
│   ├── market_scanner.py  # Gamma API market fetcher + filter
│   ├── news_engine.py     # Multi-source news aggregator + shock detector
│   ├── ai_analyst.py      # Groq AI probability analysis
│   ├── signal_detector.py # Edge detection → typed trade signals
│   ├── trade_executor.py  # CLOB order placement + exit management
│   ├── risk_manager.py    # Kelly sizing + all risk rules
│   ├── database.py        # SQLite logging
│   ├── notifier.py        # Windows toast + log file notifications
│   └── dashboard.py       # Rich terminal dashboard
├── streamlit_app.py       # Streamlit web dashboard (deployable to streamlit.io)
├── requirements.txt
├── .env                   # Your secrets (never commit this)
└── .env.template          # Copy this to .env and fill in values
```

---

## 🚀 Setup Guide

### Step 1 — Python Environment

```powershell
# Create a virtual environment (recommended)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install all dependencies
pip install -r requirements.txt
```

### Step 2 — Get a Free Groq API Key

1. Go to [https://console.groq.com](https://console.groq.com)
2. Sign up for a free account
3. Navigate to **API Keys** → **Create API Key**
4. Copy the key into `.env` as `GROQ_API_KEY`

> **Free tier:** 14,400 requests/day — more than enough for this bot's 10-minute scan cycles.

### Step 3 — Get Polymarket API Credentials

1. Go to [https://polymarket.com](https://polymarket.com) and create an account
2. Connect a **MetaMask wallet** (not email login — you need an EOA wallet)
3. Navigate to **Profile → Settings → Cash → Export Key**
4. Copy your private key into `.env` as `POLYMARKET_PRIVATE_KEY`
5. Copy your wallet address as `POLYMARKET_FUNDER_ADDRESS`
6. Leave `POLYMARKET_API_KEY/SECRET/PASSPHRASE` **blank** — the bot auto-derives them on first run

> **Note:** If you use Polymarket's email/social login, set `SIGNATURE_TYPE=1` in `.env`.

### Step 4 — Get Free Reddit API Credentials

1. Go to [https://www.reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Click **"create another app…"**
3. Select **"script"** type
4. Set redirect URI to `http://localhost:8080`
5. Copy **client_id** (under the app name) and **client_secret** into `.env`

### Step 5 — Configure `.env`

Copy the `.env` template values and fill in:

```env
GROQ_API_KEY=gsk_...
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_FUNDER_ADDRESS=0x...
REDDIT_CLIENT_ID=abc123
REDDIT_CLIENT_SECRET=xyz789
REDDIT_USER_AGENT=PolyEdgeAI/1.0 by u/yourusername
STARTING_CAPITAL=100.0
DRY_RUN=true          # ← Start here! Paper trade first.
```

### Step 6 — Fund Your Polymarket Wallet

1. Buy **USDC** on Coinbase, Binance, or Kraken
2. Bridge USDC to **Polygon (MATIC) network** using [https://wallet.polygon.technology](https://wallet.polygon.technology)
3. Send USDC to your Polymarket wallet address
4. Verify the balance appears in Polymarket → Profile → Portfolio

---

## ▶️ Running the Bot

### Terminal Dashboard (Primary)

```powershell
cd polymarket\polyedge
python main.py
```

You'll see a full-screen Rich terminal dashboard refreshing every 30 seconds.

### Streamlit Web Dashboard (Optional)

```powershell
cd polymarket
streamlit run streamlit_app.py
```

Then open [http://localhost:8501](http://localhost:8501) in your browser.

**To deploy free on Streamlit Cloud:**

1. Push your repo to GitHub (make sure `.env` is in `.gitignore`!)
2. Go to [https://streamlit.io/cloud](https://streamlit.io/cloud)
3. Connect your GitHub repo, set the main file to `streamlit_app.py`
4. Add your secrets in **Settings → Secrets** (same key-value pairs as `.env`)

---

## ⚙️ Key Configuration (config.py)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DRY_RUN` | `true` | Paper trade mode — no real orders placed |
| `MIN_EDGE_AFTER_FEE` | `7%` | Minimum AI edge after 2% Polymarket fee |
| `MAX_SINGLE_TRADE_PCT` | `8%` | Max bet size as % of capital |
| `MAX_OPEN_POSITIONS` | `4` | Max simultaneous open positions |
| `STOP_LOSS_PCT` | `50%` | Exit if position value drops 50% |
| `TAKE_PROFIT_PROBABILITY` | `85%` | Exit YES positions when price hits 85% |
| `DAILY_LOSS_LIMIT` | `-$15` | Stop trading for the day if PnL < -$15 |
| `KELLY_FRACTION` | `0.5` | Half-Kelly sizing for safety |
| `SCANNER_MIN_VOLUME` | `$5,000` | Minimum market volume |
| `SCANNER_MIN_LIQUIDITY` | `$1,000` | Minimum market liquidity |

---

## 💡 How The Edge Detection Works

```
1. Market scanner pulls top markets sorted by volume (every 10 min)
2. News engine fetches latest headlines from 6+ sources (every 3 min)
3. AI analyst sends prompt to Groq:
   - Given market question + description + news → estimate true probability
4. Signal detector: if AI_probability - market_price > 7% → BUY signal
5. Risk manager: Kelly criterion sizing, exposure limits, portfolio checks
6. Trade executor: place limit order at AI_price - 1% (get better fill)
7. Continuous monitoring: stop-loss at -50%, take-profit at 85%
```

### The Shock Detection Edge

News hits RSS feeds **5-15 minutes before Polymarket prices move**. When 3+ headlines about the same market appear within 10 minutes:

1. Bot flags `BREAKING_NEWS_SHOCK`
2. Triggers rapid Groq re-analysis
3. If urgency=`IMMEDIATE` and probability shift >10% → automatic trade

This is your **primary edge window**.

---

## 📊 Target Strategy

- **Starting capital:** $100
- **Trade frequency:** 2-5 trades per week (quality over quantity)
- **Focus markets:** Politics, Crypto, Economics (highest volume, most news-driven)
- **Target edge:** 7%+ after fees per trade
- **Example:** Market priced at 40% YES, AI estimates 52% → BUY YES at $0.40, exit at $0.80+ → ~100% ROI on position

---

## 🔧 Requirements

- Python 3.10+
- Windows 10/11 (Linux/macOS also works)
- 8GB RAM (bot uses ~200MB)
- Internet connection
- All APIs free — $0/month operating cost

---

## 📝 Logs

- `polyedge/polyedge.log` — Full system log
- `polyedge/notifications.log` — All trade notifications
- `polyedge/polyedge.db` — SQLite database (signals, trades, performance)

---

## 🔒 Security

- Private key is stored only in `.env` — never transmitted anywhere except Polymarket's own API
- `.env` is in `.gitignore` — never committed to version control
- The bot uses non-custodial signing — your key never leaves your machine

---

## ⚠️ Risk Warnings

1. **Paper trade first** — run with `DRY_RUN=true` for at least 1 week
2. AI probability estimates are not guarantees
3. Prediction markets can be illiquid — always check the spread
4. Polymarket charges 2% fee per trade — factored into minimum edge requirement
5. Near-expiry markets (< 24h) are excluded — high volatility risk
6. Maximum $15/day loss limit — bot stops automatically
