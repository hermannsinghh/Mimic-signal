"""Options market unusual activity adapter — leading indicator of company events.

Requires UNUSUAL_WHALES_KEY or CBOE_KEY environment variable.
Public data only — no dark pool access.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from mimic_signal.signal import Signal
from mimic_signal.sources.base import SignalSource

logger = logging.getLogger(__name__)

_UW_URL = "https://api.unusualwhales.com/api"

# Put/call ratio threshold for unusual activity
_PC_RATIO_THRESHOLD = 2.5   # 2.5× normal → signal
_VOLUME_SPIKE_THRESHOLD = 3.0  # 3× average daily volume


class OptionsSource(SignalSource):
    """Screens for unusual options activity as a leading indicator.

    Uses public options flow data (Unusual Whales API).
    Very high signal quality — money is talking.
    Typical lead time: 1-3 weeks before company-specific material events.
    """

    name = "options"
    poll_interval = 900   # 15 minutes (market hours)
    delay_hours = 0.0

    def __init__(self) -> None:
        self._api_key: str | None = os.getenv("UNUSUAL_WHALES_KEY")
        self._seen: set[str] = set()

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def poll(self) -> list[Signal]:
        if not self.is_available():
            logger.debug("Options: no API key configured (paid feature), skipping")
            return []
        try:
            flow = await self._fetch_unusual_flow()
        except Exception as exc:
            logger.warning("Options: fetch failed: %s", exc)
            return []

        signals: list[Signal] = []
        for item in flow:
            signal = self._evaluate_flow(item)
            if signal:
                signals.append(signal)
        return signals

    async def _fetch_unusual_flow(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=30,
            headers={"Authorization": f"Bearer {self._api_key}"},
        ) as client:
            resp = await client.get(f"{_UW_URL}/option-trades/flow-alerts")
            resp.raise_for_status()
        return resp.json().get("data", [])

    def _evaluate_flow(self, item: dict[str, Any]) -> Signal | None:
        ticker = item.get("ticker", "")
        put_call = item.get("put_call", "").upper()
        volume = float(item.get("volume", 0))
        avg_volume = float(item.get("avg_volume", 1))
        premium = float(item.get("premium", 0))
        expiry = item.get("expiry", "")

        if avg_volume == 0:
            return None
        vol_ratio = volume / avg_volume
        if vol_ratio < _VOLUME_SPIKE_THRESHOLD:
            return None

        flow_id = f"{ticker}:{put_call}:{expiry}"
        if flow_id in self._seen:
            return None
        self._seen.add(flow_id)

        # Unusual puts are stronger signal (downside risk)
        if put_call == "PUT":
            severity = min(0.5 + (vol_ratio - 3) * 0.05, 0.90)
            description = (
                f"Unusual PUT buying on {ticker}: {vol_ratio:.1f}× average volume. "
                f"${premium/1e6:.1f}M premium. Expiry: {expiry}. "
                "Historically precedes material negative events by 1-3 weeks."
            )
        else:
            severity = min(0.4 + (vol_ratio - 3) * 0.04, 0.75)
            description = (
                f"Unusual CALL buying on {ticker}: {vol_ratio:.1f}× average volume. "
                f"${premium/1e6:.1f}M premium. Expiry: {expiry}. "
                "May indicate expected positive catalyst."
            )

        return Signal(
            title=f"[Options] Unusual {put_call} activity — {ticker}",
            description=description,
            category="company_event",
            severity=round(severity, 3),
            confidence=0.75,
            source=self.name,
            source_url=f"https://unusualwhales.com/flow/{ticker}",
            detected_at=datetime.now(timezone.utc),
            event_date=datetime.now(timezone.utc),
            affected_sectors=["finance"],
            affected_geographies=["US"],
            keywords=[ticker.lower(), "options", put_call.lower(), "unusual flow"],
        )
