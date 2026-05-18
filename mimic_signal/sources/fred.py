"""FRED economic release calendar — CPI, GDP, jobs, FOMC, and more."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from mimic_signal.signal import Signal
from mimic_signal.sources.base import SignalSource

logger = logging.getLogger(__name__)

_RELEASES_URL = "https://api.stlouisfed.org/fred/releases/dates"
_RELEASE_URL = "https://api.stlouisfed.org/fred/release/dates"
_SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"

# Key FRED release IDs and their economic significance
_KEY_RELEASES: dict[int, dict[str, Any]] = {
    10:  {"name": "Consumer Price Index",        "severity": 0.80, "sectors": ["macro", "consumer"], "category": "macro"},
    50:  {"name": "Employment Situation",         "severity": 0.85, "sectors": ["macro", "labor"],    "category": "macro"},
    53:  {"name": "Gross Domestic Product",       "severity": 0.85, "sectors": ["macro"],             "category": "macro"},
    54:  {"name": "Personal Consumption",         "severity": 0.70, "sectors": ["macro", "consumer"], "category": "macro"},
    31:  {"name": "Producer Price Index",         "severity": 0.70, "sectors": ["macro", "supply_chain"], "category": "supply_chain"},
    19:  {"name": "ISM Manufacturing PMI",        "severity": 0.65, "sectors": ["manufacturing"],     "category": "supply_chain"},
    88:  {"name": "Retail Sales",                 "severity": 0.65, "sectors": ["retail", "consumer"],"category": "macro"},
    326: {"name": "FOMC Statement",               "severity": 0.90, "sectors": ["finance", "macro"],  "category": "macro"},
    33:  {"name": "Industrial Production",        "severity": 0.60, "sectors": ["manufacturing"],     "category": "macro"},
    175: {"name": "Housing Starts",               "severity": 0.55, "sectors": ["real_estate"],       "category": "macro"},
}


class FREDSource(SignalSource):
    """Watches FRED release calendar for scheduled economic data surprises.

    Without a FRED_API_KEY environment variable, fires a scheduled-release
    warning signal when a key release date arrives.
    With a key, fetches the actual release value and computes a surprise score.
    """

    name = "fred"
    poll_interval = 3600  # hourly — releases are calendar-driven
    delay_hours = 0.0     # FRED releases are public and scheduled — no delay needed

    def __init__(self) -> None:
        self._api_key: str | None = os.getenv("FRED_API_KEY")
        self._fired_releases: set[str] = set()

    def is_available(self) -> bool:
        return True  # no key needed for basic calendar mode

    async def poll(self) -> list[Signal]:
        if self._api_key:
            return await self._poll_with_api()
        return await self._poll_calendar_mode()

    async def _poll_calendar_mode(self) -> list[Signal]:
        """Fire a signal when today is a known scheduled release day."""
        today = datetime.now(timezone.utc).date()
        signals: list[Signal] = []

        for release_id, meta in _KEY_RELEASES.items():
            fire_key = f"{release_id}:{today}"
            if fire_key in self._fired_releases:
                continue
            try:
                release_dates = await self._fetch_release_dates(release_id)
            except Exception as exc:
                logger.debug("FRED: could not fetch release %d dates: %s", release_id, exc)
                continue

            if today.isoformat() in release_dates:
                self._fired_releases.add(fire_key)
                signals.append(
                    Signal(
                        title=f"[FRED] Scheduled release: {meta['name']}",
                        description=(
                            f"The {meta['name']} is scheduled for release today. "
                            "Watch for surprise magnitude relative to consensus estimates."
                        ),
                        category=meta["category"],
                        severity=meta["severity"] * 0.7,  # pending — not yet released
                        confidence=0.95,
                        source=self.name,
                        source_url=f"https://fred.stlouisfed.org/releases/{release_id}",
                        detected_at=datetime.now(timezone.utc),
                        event_date=datetime.now(timezone.utc),
                        affected_sectors=meta["sectors"],
                        affected_geographies=["US"],
                        keywords=[meta["name"].lower(), "economic release", "calendar"],
                    )
                )

        return signals

    async def _poll_with_api(self) -> list[Signal]:
        """Fetch latest observations and compute surprise vs prior."""
        today = datetime.now(timezone.utc).date()
        signals: list[Signal] = []

        for release_id, meta in _KEY_RELEASES.items():
            fire_key = f"{release_id}:{today}:api"
            if fire_key in self._fired_releases:
                continue
            try:
                surprise = await self._compute_surprise(release_id)
            except Exception as exc:
                logger.debug("FRED: surprise compute failed for %d: %s", release_id, exc)
                continue
            if surprise is None:
                continue

            self._fired_releases.add(fire_key)
            abs_surprise = abs(surprise)
            severity = min(meta["severity"] * (0.5 + abs_surprise), 1.0)

            direction = "above" if surprise > 0 else "below"
            signals.append(
                Signal(
                    title=f"[FRED] {meta['name']} — {abs_surprise:.1%} {direction} prior",
                    description=(
                        f"{meta['name']} released with a {abs_surprise:.1%} deviation "
                        f"from the prior reading ({direction} expectations)."
                    ),
                    category=meta["category"],
                    severity=round(severity, 3),
                    confidence=0.95,
                    source=self.name,
                    source_url=f"https://fred.stlouisfed.org/releases/{release_id}",
                    detected_at=datetime.now(timezone.utc),
                    event_date=datetime.now(timezone.utc),
                    affected_sectors=meta["sectors"],
                    affected_geographies=["US"],
                    keywords=[meta["name"].lower(), "economic surprise", "macro"],
                )
            )

        return signals

    async def _fetch_release_dates(self, release_id: int) -> list[str]:
        params = {
            "release_id": release_id,
            "file_type": "json",
            "limit": 10,
            "sort_order": "desc",
        }
        if self._api_key:
            params["api_key"] = self._api_key
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_RELEASE_URL, params=params)
            resp.raise_for_status()
        data = resp.json()
        return [d["date"] for d in data.get("release_dates", [])]

    async def _compute_surprise(self, release_id: int) -> float | None:
        """Return (latest - prior) / abs(prior) as a surprise fraction."""
        # Fetch series for this release — simplified: use a known series ID
        series_map: dict[int, str] = {
            10: "CPIAUCSL",    # CPI
            50: "UNRATE",      # Unemployment rate
            53: "GDP",         # GDP
            31: "PPIACO",      # PPI
            88: "RSAFS",       # Retail sales
        }
        series_id = series_map.get(release_id)
        if not series_id:
            return None

        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "limit": 3,
            "sort_order": "desc",
            "observation_start": (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).strftime("%Y-%m-%d"),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_SERIES_URL, params=params)
            resp.raise_for_status()
        obs = resp.json().get("observations", [])
        valid = [float(o["value"]) for o in obs if o["value"] not in (".", "")]
        if len(valid) < 2:
            return None
        latest, prior = valid[0], valid[1]
        if prior == 0:
            return None
        return (latest - prior) / abs(prior)
