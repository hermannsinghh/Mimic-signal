"""Twitter/X financial discussion adapter — earliest detection, highest noise.

Requires TWITTER_BEARER_TOKEN environment variable (X API Basic tier, ~$100/month).
Use with high confidence threshold; cross-validate with GDELT.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from mimic_signal.signal import Signal
from mimic_signal.sources.base import SignalSource

logger = logging.getLogger(__name__)

_TWITTER_URL = "https://api.twitter.com/2/tweets/search/recent"

# Queries that catch financial risk signals
_SEARCH_QUERIES = [
    "(supply chain OR port congestion OR shipping delay) lang:en -is:retweet",
    "(sanctions OR trade war OR tariff) (supply OR trade) lang:en -is:retweet",
    "(factory fire OR plant shutdown OR force majeure) lang:en -is:retweet",
    "(earnings miss OR revenue warning OR guidance cut) lang:en -is:retweet",
]

_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
_VIRAL_THRESHOLD = 100   # retweets or likes to be considered signal-worthy
_MIN_MENTIONS = 3        # ticker/keyword must appear in multiple tweets


class TwitterSource(SignalSource):
    """Monitors X (Twitter) for early financial and supply chain signals.

    Fastest possible detection but highest noise. Always cross-validate.
    Typical lead time: hours ahead of traditional news coverage.
    """

    name = "twitter"
    poll_interval = 1800  # 30 minutes (rate limit conscious)
    delay_hours = 24.0    # open-source delay

    def __init__(self) -> None:
        self._bearer: str | None = os.getenv("TWITTER_BEARER_TOKEN")
        self._seen_ids: set[str] = set()
        self._keyword_counts: dict[str, int] = {}

    def is_available(self) -> bool:
        return bool(self._bearer)

    async def poll(self) -> list[Signal]:
        if not self.is_available():
            logger.debug("Twitter: no bearer token configured (paid feature), skipping")
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.delay_hours)
        all_tweets: list[dict[str, Any]] = []
        for query in _SEARCH_QUERIES:
            try:
                tweets = await self._search(query)
                all_tweets.extend(tweets)
            except Exception as exc:
                logger.debug("Twitter: query failed: %s", exc)

        # Cluster tweets by keyword to find trending topics
        clusters = self._cluster_tweets(all_tweets)
        signals: list[Signal] = []

        for keyword, tweets in clusters.items():
            if len(tweets) < _MIN_MENTIONS:
                continue
            representative = max(tweets, key=lambda t: t.get("public_metrics", {}).get("retweet_count", 0))
            tweet_id = representative.get("id", "")
            if tweet_id in self._seen_ids:
                continue

            created_at = self._parse_date(representative.get("created_at"))
            if created_at and created_at > cutoff:
                continue

            self._seen_ids.add(tweet_id)
            metrics = representative.get("public_metrics", {})
            virality = metrics.get("retweet_count", 0) + metrics.get("like_count", 0)
            if virality < _VIRAL_THRESHOLD and len(tweets) < 5:
                continue

            severity = min(0.35 + len(tweets) * 0.05 + virality / 1000 * 0.1, 0.70)
            tickers = list({
                t for tw in tweets
                for t in _TICKER_RE.findall(tw.get("text", ""))
            })

            signals.append(
                Signal(
                    title=f"[Twitter] Trending financial signal — {keyword[:60]}",
                    description=(
                        f"{len(tweets)} tweets mentioning '{keyword}'. "
                        f"Virality score: {virality}. "
                        f"Tickers mentioned: {', '.join(tickers[:5]) or 'none'}. "
                        "Cross-validate with other sources before acting."
                    ),
                    category=self._categorize(keyword),
                    severity=round(severity, 3),
                    confidence=0.40,  # social media = low base confidence
                    source=self.name,
                    source_url=f"https://twitter.com/search?q={keyword.replace(' ', '+')}",
                    detected_at=datetime.now(timezone.utc),
                    event_date=created_at or datetime.now(timezone.utc),
                    affected_sectors=self._infer_sectors(keyword),
                    affected_geographies=[],
                    keywords=[keyword] + [t.lower() for t in tickers[:5]],
                )
            )

        if len(self._seen_ids) > 50_000:
            self._seen_ids = set(list(self._seen_ids)[-25_000:])

        return signals

    async def _search(self, query: str) -> list[dict[str, Any]]:
        params = {
            "query": query,
            "max_results": 100,
            "tweet.fields": "created_at,public_metrics,entities",
            "expansions": "author_id",
        }
        async with httpx.AsyncClient(
            timeout=30,
            headers={"Authorization": f"Bearer {self._bearer}"},
        ) as client:
            resp = await client.get(_TWITTER_URL, params=params)
            resp.raise_for_status()
        return resp.json().get("data", [])

    def _cluster_tweets(self, tweets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        clusters: dict[str, list[dict[str, Any]]] = {}
        keyword_groups = [
            ("supply chain", ["supply chain", "port congestion", "shipping delay"]),
            ("sanctions", ["sanctions", "trade war", "tariff"]),
            ("factory disruption", ["factory fire", "plant shutdown", "force majeure"]),
            ("earnings warning", ["earnings miss", "revenue warning", "guidance cut"]),
        ]
        for tweet in tweets:
            text = (tweet.get("text") or "").lower()
            for cluster_name, keywords in keyword_groups:
                if any(kw in text for kw in keywords):
                    clusters.setdefault(cluster_name, []).append(tweet)
                    break
        return clusters

    def _parse_date(self, date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            from dateutil import parser as dp
            dt = dp.parse(date_str)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _categorize(self, keyword: str) -> str:
        if "supply chain" in keyword or "shipping" in keyword:
            return "supply_chain"
        if "sanctions" in keyword or "trade war" in keyword:
            return "geopolitical"
        if "earnings" in keyword or "revenue" in keyword:
            return "company_event"
        return "macro"

    def _infer_sectors(self, keyword: str) -> list[str]:
        if "supply chain" in keyword or "shipping" in keyword:
            return ["supply_chain", "retail"]
        if "factory" in keyword or "plant" in keyword:
            return ["manufacturing"]
        return ["general"]
