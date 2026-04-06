"""
PolyEdge AI — Configuration Module
All settings, API keys, and risk parameters live here.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Credentials ─────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")
POLYMARKET_FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")

# Optional data source keys (free sign-ups)
FRED_API_KEY  = os.getenv("FRED_API_KEY", "")    # fred.stlouisfed.org/docs/api/api_key.html
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")   # gnews.io (100 req/day free)

# ─── Network / API Endpoints ──────────────────────────────────────────────────
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE  = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137

# ─── Groq / AI Settings ───────────────────────────────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_MAX_TOKENS = 512
GROQ_TEMPERATURE = 0.2
AI_CACHE_TTL_SECONDS = 480          # 8 minutes — cache AI results per market

# ─── Market Scanner Settings ─────────────────────────────────────────────────
SCANNER_MARKET_LIMIT = 500          # fetch up to 500 from Gamma per sort order
SCANNER_TOP_N = 15                  # Return 15 markets
SCANNER_MIN_VOLUME = 500            # Bare minimum. Scoring handles the rest.
SCANNER_MIN_LIQUIDITY = 500         # Bare minimum. Scoring handles the rest.
SCANNER_MIN_HOURS_TO_EXPIRY = 48    # ignore markets expiring within 48h
SCANNER_MAX_CATEGORY_SHARE = 0.40   # Max 40% of markets from a single category
TARGET_CATEGORIES = ["Politics", "Crypto", "Economics", "Finance", "Sports"]

# ─── News Engine Settings ────────────────────────────────────────────────────
NEWS_POLL_INTERVAL_SECONDS = 180    # 3 minutes
NEWS_SHOCK_WINDOW_SECONDS  = 600    # 10 minutes for shock detection
NEWS_SHOCK_THRESHOLD       = 3      # 3+ headlines → BREAKING_NEWS_SHOCK
NEWS_MAX_HEADLINES_PER_MARKET = 5
REDDIT_SUBREDDITS = []   # Reddit removed — API policy changes made free access unreliable

RSS_FEEDS = [
    # Major news wires
    "https://feeds.reuters.com/reuters/topNews",
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.ap.org/rss/apf-topnews",
    "https://www.aljazeera.com/xml/rss/all.xml",
    # Politics / US
    "https://rss.politico.com/politics-news.xml",
    # Finance / Crypto
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    # Reddit public RSS (no API key needed!)
    "https://www.reddit.com/r/worldnews/.rss",
    "https://www.reddit.com/r/politics/.rss",
    "https://www.reddit.com/r/CryptoCurrency/.rss",
    "https://www.reddit.com/r/Economics/.rss",
    "https://www.reddit.com/r/geopolitics/.rss",
]

SOURCE_CREDIBILITY = {
    "reuters.com":    1.0,
    "bbc.co.uk":      0.95,
    "bbc.com":        0.95,
    "ap.org":         1.0,
    "apnews.com":     1.0,
    "aljazeera.com":  0.85,
    "politico.com":   0.88,
    "coindesk.com":   0.82,
    "google.com":     0.80,
    "reddit.com":     0.65,
    "wikipedia.org":  0.70,
    "hackernews":     0.72,
    "metaculus.com":  0.95,  # calibrated human forecasters
    "fred":           1.0,   # Federal Reserve data = ground truth
    "coingecko":      0.90,
    "default":        0.65,
}

# ─── Metaculus Settings ───────────────────────────────────────────────────────
METACULUS_MIN_FORECASTERS = 5      # skip if fewer than 5 forecasters
METACULUS_MIN_SIMILARITY  = 0.35   # keyword overlap threshold

# ─── FRED Economic Data ───────────────────────────────────────────────────────
# Series to fetch for economic markets (empty = feature disabled if no key)
FRED_SERIES = {
    "FEDFUNDS":  "Federal Funds Rate",
    "CPIAUCSL":  "Consumer Price Index (inflation)",
    "UNRATE":    "US Unemployment Rate",
    "GDP":       "US GDP",
}

# ─── CoinGecko Crypto Prices ──────────────────────────────────────────────────
COINGECKO_COINS = ["bitcoin", "ethereum", "solana", "dogecoin", "ripple"]
COINGECKO_ENABLED = True  # No API key needed

# ─── Signal Detection Thresholds ────────────────────────────────────────────
STRONG_BUY_EDGE_THRESHOLD    = 8.0   # % edge for STRONG_BUY
BUY_EDGE_THRESHOLD           = 5.0   # % edge for BUY
STRONG_BUY_MIN_VOLUME        = 10_000
SHOCK_MIN_PROBABILITY_SHIFT  = 10.0  # % shift to trigger shock trade

# ─── Risk Management Parameters ──────────────────────────────────────────────
CAPITAL_TOTAL               = float(os.getenv("STARTING_CAPITAL", "100.0"))
MAX_SINGLE_TRADE_PCT        = 0.08   # 8% of capital
MAX_OPEN_POSITIONS          = 4
MAX_EXPOSURE_PER_CATEGORY   = 0.25   # 25% of capital
MIN_EDGE_AFTER_FEE          = 7.0    # % minimum edge after 2% Polymarket fee
STOP_LOSS_PCT               = 0.50   # exit if position drops 50%
TAKE_PROFIT_PROBABILITY     = 85.0   # exit when market probability reaches 85%
TAKE_PROFIT_ENTRY_CEILING   = 60.0   # only take profit if entered below 60%
DAILY_LOSS_LIMIT            = -15.0  # stop trading if daily P&L < -$15
MIN_MARKET_LIQUIDITY        = 2_000  # never trade below this liquidity (USDC)
MIN_TIME_TO_RESOLUTION_HRS  = 24    # avoid last-minute volatility
POLYMARKET_FEE_PCT          = 2.0   # 2% per trade
KELLY_FRACTION              = 0.5   # half-Kelly for safety

# ─── Trade Executor Settings ─────────────────────────────────────────────────
ORDER_LIMIT_OFFSET_PCT      = 0.01   # buy 1% below AI estimate (limit orders)
STALE_ORDER_MINUTES         = 30     # cancel unfilled orders older than 30 min
EXIT_CHECK_INTERVAL_SECONDS = 300    # check stops every 5 minutes
SIGNATURE_TYPE              = int(os.getenv("SIGNATURE_TYPE", "0"))  # 0=EOA, 1=Proxy

# ─── Database ────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "polyedge.db")

# ─── Dashboard ───────────────────────────────────────────────────────────────
DASHBOARD_REFRESH_SECONDS = 30

# ─── Dry Run Mode ────────────────────────────────────────────────────────────
# Set DRY_RUN=True to simulate trades without real orders. ALWAYS start here!
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

def validate_config() -> list[str]:
    """Validate critical config values and return list of warnings."""
    warnings = []
    if not GROQ_API_KEY:
        warnings.append("GROQ_API_KEY is not set — AI analysis will fail.")
    if not POLYMARKET_PRIVATE_KEY:
        warnings.append("POLYMARKET_PRIVATE_KEY not set — trading disabled.")
    if DRY_RUN:
        warnings.append("DRY_RUN=True — No real orders will be placed.")
    return warnings
