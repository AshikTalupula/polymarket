"""
PolyEdge AI — News Engine
Aggregates real-time news from all free sources, scores headlines for
relevance, and detects breaking-news shock events.
"""
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import requests

import config

logger = logging.getLogger(__name__)

# Optional PRAW — gracefully degraded if not configured
try:
    import praw
    _PRAW_AVAILABLE = True
except ImportError:
    _PRAW_AVAILABLE = False


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

class NewsAggregator:
    def __init__(self):
        self._seen_hashes:  set[str] = set()
        self._all_headlines: list[Headline] = []
        self._news_cache:   dict[str, NewsContext] = {}
        self._reddit: Optional[object] = None
        self._init_reddit()

    def _init_reddit(self):
        if not _PRAW_AVAILABLE:
            return
        if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
            logger.warning("Reddit credentials missing — Reddit source disabled.")
            return
        try:
            self._reddit = praw.Reddit(
                client_id=config.REDDIT_CLIENT_ID,
                client_secret=config.REDDIT_CLIENT_SECRET,
                user_agent=config.REDDIT_USER_AGENT,
                read_only=True,
            )
            logger.info("Reddit client initialised.")
        except Exception as e:
            logger.error("Reddit init failed: %s", e)

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

    def _fetch_reddit(self, keywords: list[str]) -> list[Headline]:
        if not self._reddit:
            return []
        headlines = []
        keyword_str = " ".join(keywords[:3]).lower()
        for sub_name in config.REDDIT_SUBREDDITS:
            try:
                sub = self._reddit.subreddit(sub_name)
                for post in list(sub.new(limit=30)) + list(sub.hot(limit=20)):
                    title_lower = post.title.lower()
                    if not any(kw in title_lower for kw in keyword_str.split()):
                        continue
                    pub = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                    h = Headline(
                        title=post.title,
                        url=f"https://reddit.com{post.permalink}",
                        source=f"r/{sub_name}",
                        published=pub,
                        credibility=config.SOURCE_CREDIBILITY["reddit.com"],
                    )
                    headlines.append(h)
            except Exception as e:
                logger.debug("Reddit fetch error r/%s: %s", sub_name, e)
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

        # Standard RSS feeds
        for feed_url in config.RSS_FEEDS:
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
        Also polls Google News and Reddit for market-specific terms.
        """
        market_id = market["market_id"]
        question  = market["question"]
        keywords  = self._extract_keywords(question)

        # Fetch market-specific news from Google News + Reddit
        google_news = self._fetch_google_news(keywords)
        reddit_news = self._fetch_reddit(keywords)
        specific    = self._deduplicate(google_news + reddit_news)

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
