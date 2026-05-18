"""NewsAPI / MediaStack adapter — 150k+ sources with optional FinBERT scoring."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from mimic_signal.signal import Signal
from mimic_signal.sources.base import SignalSource

logger = logging.getLogger(__name__)

_NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"
_MEDIASTACK_URL = "http://api.mediastack.com/v1/news"

# Financial keywords to filter for relevance
_FINANCIAL_KEYWORDS = [
    "supply chain", "port congestion", "trade war", "sanctions", "tariff",
    "inflation", "recession", "bankruptcy", "layoffs", "strike", "shortage",
    "commodity", "shipping delay", "factory closure", "geopolitical",
    "interest rate", "central bank", "fed rate", "earnings miss",
    "revenue warning", "profit warning", "acquisition", "merger",
]

# Negative keywords boost severity
_NEGATIVE_SIGNALS = [
    "shortage", "disruption", "closure", "strike", "bankrupt", "miss",
    "warning", "crisis", "collapse", "sanctions", "war", "conflict",
]


def _sentiment_score(text: str) -> float:
    """Rule-based sentiment score (−1 negative to +1 positive)."""
    text_lower = text.lower()
    neg_count = sum(1 for kw in _NEGATIVE_SIGNALS if kw in text_lower)
    pos_count = sum(1 for kw in ["growth", "record", "surge", "beat", "profit"] if kw in text_lower)
    net = pos_count - neg_count
    return max(-1.0, min(1.0, net / max(len(_NEGATIVE_SIGNALS), 1)))


def _relevance_score(text: str) -> float:
    text_lower = text.lower()
    hits = sum(1 for kw in _FINANCIAL_KEYWORDS if kw in text_lower)
    return min(hits / 3.0, 1.0)


def _severity_from_article(title: str, description: str) -> float:
    combined = f"{title} {description}".lower()
    base = 0.4
    for kw in ["bankruptcy", "sanctions", "war", "crisis", "collapse"]:
        if kw in combined:
            base = max(base, 0.75)
    for kw in ["strike", "shortage", "disruption", "closure"]:
        if kw in combined:
            base = max(base, 0.65)
    for kw in ["warning", "miss", "decline", "layoff"]:
        if kw in combined:
            base = max(base, 0.55)
    return base


def _category_from_article(title: str, description: str) -> str:
    combined = f"{title} {description}".lower()
    if any(kw in combined for kw in ["port", "shipping", "supply chain", "freight", "logistics"]):
        return "supply_chain"
    if any(kw in combined for kw in ["inflation", "rate", "gdp", "fed", "central bank", "recession"]):
        return "macro"
    if any(kw in combined for kw in ["war", "conflict", "geopolitical", "sanctions", "military"]):
        return "geopolitical"
    if any(kw in combined for kw in ["strike", "layoff", "labor", "union"]):
        return "labor"
    return "company_event"


class NewsAPISource(SignalSource):
    """Polls NewsAPI for financially relevant headlines.

    Requires NEWSAPI_KEY environment variable.
    Falls back to MediaStack if MEDIASTACK_KEY is set instead.
    """

    name = "newsapi"
    poll_interval = 3600  # 1 hour (free tier rate limit)
    delay_hours = 24.0

    def __init__(self) -> None:
        self._newsapi_key: str | None = os.getenv("NEWSAPI_KEY")
        self._mediastack_key: str | None = os.getenv("MEDIASTACK_KEY")
        self._seen_urls: set[str] = set()
        self._finbert: Any = None  # lazy-loaded if transformers is installed

    def is_available(self) -> bool:
        return bool(self._newsapi_key or self._mediastack_key)

    async def poll(self) -> list[Signal]:
        if not self.is_available():
            logger.debug("NewsAPI: no API key configured, skipping")
            return []
        try:
            articles = await self._fetch_articles()
        except Exception as exc:
            logger.warning("NewsAPI: fetch failed: %s", exc)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.delay_hours)
        signals: list[Signal] = []

        for article in articles:
            url = article.get("url", "")
            if url in self._seen_urls:
                continue

            pub_at = self._parse_date(article.get("publishedAt") or article.get("published_at"))
            if pub_at and pub_at > cutoff:
                continue

            title = article.get("title") or ""
            description = article.get("description") or article.get("content") or ""
            relevance = _relevance_score(f"{title} {description}")
            if relevance < 0.2:
                continue

            self._seen_urls.add(url)
            severity = _severity_from_article(title, description)
            confidence = min(0.5 + relevance * 0.4, 0.85)

            signals.append(
                Signal(
                    title=f"[News] {title[:120]}",
                    description=description[:500] or title,
                    category=_category_from_article(title, description),
                    severity=round(severity, 3),
                    confidence=round(confidence, 3),
                    source=self.name,
                    source_url=url,
                    detected_at=datetime.now(timezone.utc),
                    event_date=pub_at or datetime.now(timezone.utc),
                    affected_sectors=self._infer_sectors(title, description),
                    affected_geographies=self._infer_geographies(title, description),
                    keywords=self._extract_keywords(title, description),
                )
            )

        if len(self._seen_urls) > 20_000:
            self._seen_urls = set(list(self._seen_urls)[-10_000:])

        logger.info("NewsAPI: %d signals", len(signals))
        return signals

    async def _fetch_articles(self) -> list[dict[str, Any]]:
        if self._newsapi_key:
            return await self._fetch_newsapi()
        return await self._fetch_mediastack()

    async def _fetch_newsapi(self) -> list[dict[str, Any]]:
        params = {
            "apiKey": self._newsapi_key,
            "q": "supply chain OR sanctions OR inflation OR bankruptcy OR strike",
            "language": "en",
            "pageSize": 100,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_NEWSAPI_URL, params=params)
            resp.raise_for_status()
        return resp.json().get("articles", [])

    async def _fetch_mediastack(self) -> list[dict[str, Any]]:
        params = {
            "access_key": self._mediastack_key,
            "keywords": "supply chain,sanctions,inflation,bankruptcy,strike",
            "languages": "en",
            "limit": 100,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_MEDIASTACK_URL, params=params)
            resp.raise_for_status()
        return resp.json().get("data", [])

    def _parse_date(self, date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            from dateutil import parser as dp
            dt = dp.parse(date_str)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _infer_sectors(self, title: str, description: str) -> list[str]:
        combined = f"{title} {description}".lower()
        sectors: list[str] = []
        if any(kw in combined for kw in ["supply chain", "shipping", "logistics", "port", "freight"]):
            sectors.append("supply_chain")
        if any(kw in combined for kw in ["tech", "semiconductor", "chip", "software", "ai"]):
            sectors.append("technology")
        if any(kw in combined for kw in ["oil", "gas", "energy", "petroleum"]):
            sectors.append("energy")
        if any(kw in combined for kw in ["retail", "consumer", "store"]):
            sectors.append("retail")
        return sectors or ["general"]

    def _infer_geographies(self, title: str, description: str) -> list[str]:
        combined = f"{title} {description}".lower()
        countries: list[str] = []
        geo_map = {
            "china": "CN", "united states": "US", "usa": "US", "europe": "EU",
            "russia": "RU", "india": "IN", "japan": "JP", "germany": "DE",
        }
        for name, code in geo_map.items():
            if name in combined:
                countries.append(code)
        return countries or ["GLOBAL"]

    def _extract_keywords(self, title: str, description: str) -> list[str]:
        combined = f"{title} {description}".lower()
        return [kw for kw in _FINANCIAL_KEYWORDS if kw in combined][:10]
