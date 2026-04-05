"""
PolyEdge AI — News Engine
Aggregates real-time news from all free sources, scores headlines for
relevance, and detects breaking-news shock events.

Sources (all 100% free, no API key required):
  - Reuters, BBC, AP, Al Jazeera RSS
  - Google News RSS (keyword search — no auth)
  - Hacker News API (free, no auth)
  - Wikipedia Recent Changes API
  - NPR News, The Guardian, Politico RSS
  - Crypto: CoinDesk, CoinTelegraph RSS

Note: Reddit was originally planned but their 2023/2024 API policy
changes made free app creation unreliable. HackerNews covers similar
crowd-sourced signal without any registration requirement.
"""
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import requests

import config

logger = logging.getLogger(__name__)


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class Headline:
    title:       str
    url:         str
    source:      str
    published:   datetime
    credibility: float
    url_hash:    str = field(init=False)

    def __post_init__(self):
        self.url_hash = hashlib.md5(self.url.encode()).hexdigest()

    @property
    def recency_score(self) -> float:
        """Score 0-1 based on age. <1h=1.0, 24h=0.5, 72h=0.0"""
        age_hrs = (datetime.now(timezone.utc) - self.published).total_seconds() / 3600
        if age_hrs < 1:
            return 1.0
        elif age_hrs < 24:
            return max(0.5, 1.0 - age_hrs / 48)
        return max(0.0, 0.5 - (age_hrs - 24) / 96)

    @property
    def total_score(self) -> float:
        return round(self.recency_score * 0.6 + self.credibility * 0.4, 4)


@dataclass
class NewsContext:
    market_id:     str
    market_question: str
    top_headlines: list[Headline]
    is_shock:      bool = False
    shock_headlines: list[Headline] = field(default_factory=list)
    last_updated:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_headlines_text(self, limit: int = 5) -> str:
        lines = []
        for h in self.top_headlines[:limit]:
            ts = h.published.strftime("%Y-%m-%d %H:%M UTC")
            lines.append(f"[{h.source}] {h.title} ({ts})")
        return "\n".join(lines) if lines else "No recent news found."

    def get_shock_text(self) -> str:
        return "\n".join(
            f"[{h.source}] {h.title}" for h in self.shock_headlines
        )


# ─── NewsAggregator ──────────────────────────────────────────────────────────

# Additional free RSS feeds (no auth needed)
EXTRA_RSS_FEEDS = [
    "https://feeds.npr.org/1001/rss.xml",                   # NPR Top Stories
    "https://www.theguardian.com/world/rss",                 # The Guardian World
    "https://rss.politico.com/politics-news.xml",            # Politico
    "https://www.coindesk.com/arc/outboundfeeds/rss/",       # CoinDesk (crypto)
    "https://cointelegraph.com/rss",                         # CoinTelegraph (crypto)
    "https://www.ft.com/?format=rss",                        # Financial Times
]


class NewsAggregator:
    def __init__(self):
        self._seen_hashes:  set[str] = set()
        self._all_headlines: list[Headline] = []
        self._news_cache:   dict[str, NewsContext] = {}
        logger.info(
            "News engine initialised. Sources: RSS feeds, Google News, "
            "HackerNews, Wikipedia. (Reddit removed — see module docstring)"
        )

    # ── Source Polling ──────────────────────────────────────────────────────

    def _source_credibility(self, url: str) -> float:
        for domain, score in config.SOURCE_CREDIBILITY.items():
            if domain in url:
                return score
        return config.SOURCE_CREDIBILITY["default"]

    def _parse_entry_date(self, entry) -> datetime:
        for attr in ("published_parsed", "updated_parsed"):
            val = getattr(entry, attr, None)
            if val:
                try:
                    return datetime(*val[:6], tzinfo=timezone.utc)
                except Exception:
                    pass
        return datetime.now(timezone.utc)

    def _fetch_rss(self, url: str) -> list[Headline]:
        headlines = []
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:25]:
                link = getattr(entry, "link", "")
                if not link:
                    continue
                h = Headline(
                    title=getattr(entry, "title", ""),
                    url=link,
                    source=feed.feed.get("title", url)[:40],
                    published=self._parse_entry_date(entry),
                    credibility=self._source_credibility(link),
                )
                headlines.append(h)
        except Exception as e:
            logger.debug("RSS fetch error %s: %s", url, e)
        return headlines

    def _fetch_google_news(self, keywords: list[str]) -> list[Headline]:
        query = " ".join(keywords[:5])
        url = (
            f"https://news.google.com/rss/search"
            f"?q={quote_plus(query)}&hl=en&gl=US&ceid=US:en"
        )
        return self._fetch_rss(url)

    def _fetch_hackernews(self, keywords: list[str]) -> list[Headline]:
        """
        Hacker News Algolia search API — completely free, no auth required.
        Searches HN stories matching the market keywords from the last 24h.
        """
        headlines = []
        query = " ".join(keywords[:4])
        try:
            url = "https://hn.algolia.com/api/v1/search"
            params = {
                "query":        query,
                "tags":         "story",
                "numericFilters": f"created_at_i>{int((datetime.now(timezone.utc).timestamp() - 86400))}",
                "hitsPerPage":  20,
            }
            resp = requests.get(url, params=params, timeout=10,
                                headers={"User-Agent": "PolyEdgeAI/1.0"})
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            for hit in hits:
                title = hit.get("title", "")
                hn_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"
                created = hit.get("created_at", "")
                try:
                    pub = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except Exception:
                    pub = datetime.now(timezone.utc)
                h = Headline(
                    title=title,
                    url=hn_url,
                    source="HackerNews",
                    published=pub,
                    credibility=0.70,  # HN community = reasonably credible signal
                )
                headlines.append(h)
        except Exception as e:
            logger.debug("HackerNews API error: %s", e)
        return headlines

    def _fetch_wikipedia_recent(self) -> list[Headline]:
        """Wikipedia recent changes API — catches breaking events early."""
        headlines = []
        try:
            url = (
                "https://en.wikipedia.org/w/api.php"
                "?action=query&list=recentchanges&rctype=edit|new"
                "&rcnamespace=0&rclimit=50&rcprop=title|timestamp"
                "&format=json"
            )
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "PolyEdgeAI/1.0"})
            resp.raise_for_status()
            data = resp.json()
            for change in data.get("query", {}).get("recentchanges", []):
                pub_str = change.get("timestamp", "")
                try:
                    pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pub = datetime.now(timezone.utc)
                title = change.get("title", "")
                h = Headline(
                    title=f"[Wikipedia Edit] {title}",
                    url=f"https://en.wikipedia.org/wiki/{title.replace(' ','_')}",
                    source="Wikipedia",
                    published=pub,
                    credibility=config.SOURCE_CREDIBILITY["wikipedia.org"],
                )
                headlines.append(h)
        except Exception as e:
            logger.debug("Wikipedia API error: %s", e)
        return headlines

    # ── Deduplication & Scoring ─────────────────────────────────────────────

    def _deduplicate(self, headlines: list[Headline]) -> list[Headline]:
        unique = []
        for h in headlines:
            if h.url_hash not in self._seen_hashes:
                self._seen_hashes.add(h.url_hash)
                unique.append(h)
        return unique

    @staticmethod
    def _extract_keywords(question: str) -> list[str]:
        """Extract 3-5 meaningful keywords from a market question."""
        stop_words = {
            "will", "the", "a", "an", "in", "on", "by", "at", "for",
            "of", "to", "is", "be", "are", "was", "were", "it", "this",
            "that","with","and","or","not","from","than","more","before",
            "after", "bet", "who", "what", "which", "when", "between",
        }
        words = question.replace("?", "").replace(",", "").split()
        keywords = [
            w for w in words
            if w.lower() not in stop_words and len(w) > 3
        ]
        return keywords[:5] if keywords else ["news"]

    # ── Shock Detection ─────────────────────────────────────────────────────

    def _detect_shock(self,
                      headlines: list[Headline],
                      market_id: str) -> tuple[bool, list[Headline]]:
        """
        Flag if ≥ NEWS_SHOCK_THRESHOLD headlines for this market appeared
        in the last NEWS_SHOCK_WINDOW_SECONDS.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=config.NEWS_SHOCK_WINDOW_SECONDS
        )
        recent = [h for h in headlines if h.published >= cutoff]
        is_shock = len(recent) >= config.NEWS_SHOCK_THRESHOLD
        return is_shock, recent

    # ── Public API ──────────────────────────────────────────────────────────

    def refresh_all_sources(self):
        """Poll all free news sources. Called every 3 minutes."""
        logger.info("News engine: refreshing all sources…")
        new_headlines: list[Headline] = []

        # Core RSS feeds (config)
        for feed_url in config.RSS_FEEDS:
            new_headlines.extend(self._fetch_rss(feed_url))

        # Extra RSS feeds (politics, crypto, finance)
        for feed_url in EXTRA_RSS_FEEDS:
            new_headlines.extend(self._fetch_rss(feed_url))

        # Wikipedia recent changes
        new_headlines.extend(self._fetch_wikipedia_recent())

        # Deduplicate and merge
        fresh = self._deduplicate(new_headlines)
        self._all_headlines.extend(fresh)

        # Keep only headlines from the last 24 hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        self._all_headlines = [
            h for h in self._all_headlines if h.published >= cutoff
        ]

        logger.info(
            "News engine: %d new headlines / %d total in 24h window",
            len(fresh), len(self._all_headlines)
        )

    def get_news_for_market(self, market: dict) -> NewsContext:
        """
        Build a NewsContext for a specific market using keyword matching.
        Polls Google News and HackerNews for market-specific terms.
        """
        market_id = market["market_id"]
        question  = market["question"]
        keywords  = self._extract_keywords(question)

        # Fetch market-specific news from Google News + HackerNews
        google_news = self._fetch_google_news(keywords)
        hn_news     = self._fetch_hackernews(keywords)
        specific    = self._deduplicate(google_news + hn_news)

        # Combine with global pool, filter by keyword relevance
        kw_lower = [k.lower() for k in keywords]
        all_relevant = []
        for h in (specific + self._all_headlines):
            if any(kw in h.title.lower() for kw in kw_lower):
                all_relevant.append(h)

        # Sort by total_score (recency × credibility)
        all_relevant.sort(key=lambda h: h.total_score, reverse=True)

        top = all_relevant[: config.NEWS_MAX_HEADLINES_PER_MARKET]
        is_shock, shock_heads = self._detect_shock(all_relevant, market_id)

        ctx = NewsContext(
            market_id=market_id,
            market_question=question,
            top_headlines=top,
            is_shock=is_shock,
            shock_headlines=shock_heads,
        )
        self._news_cache[market_id] = ctx

        if is_shock:
            logger.warning(
                "⚡ BREAKING_NEWS_SHOCK detected for market: %s (%d recent headlines)",
                question[:60], len(shock_heads)
            )

        return ctx

    def get_cached_news(self, market_id: str) -> Optional[NewsContext]:
        return self._news_cache.get(market_id)

    def get_all_recent_headlines(self, limit: int = 10) -> list[Headline]:
        """Return most recent N headlines across all sources for the dashboard."""
        sorted_heads = sorted(
            self._all_headlines, key=lambda h: h.published, reverse=True
        )
        return sorted_heads[:limit]
