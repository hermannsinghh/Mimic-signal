"""AIS vessel tracking adapter — port congestion and shipping lane anomalies.

Requires a paid API key from AISHub or MarineTraffic.
Set AIS_API_KEY and AIS_PROVIDER=aishub|marinetraffic.
Without credentials this source is disabled (open-source tier).
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

# Major commercial ports to monitor
_MONITORED_PORTS: dict[str, dict[str, Any]] = {
    "CNSHA": {"name": "Port of Shanghai",     "lat": 31.23, "lon": 121.47, "country": "CN"},
    "SGSIN": {"name": "Port of Singapore",    "lat": 1.26,  "lon": 103.82, "country": "SG"},
    "NLRTM": {"name": "Port of Rotterdam",    "lat": 51.93, "lon": 4.07,   "country": "NL"},
    "USLAX": {"name": "Port of Los Angeles",  "lat": 33.73, "lon": -118.27,"country": "US"},
    "USLGB": {"name": "Port of Long Beach",   "lat": 33.77, "lon": -118.22,"country": "US"},
    "DEHAM": {"name": "Port of Hamburg",      "lat": 53.55, "lon": 9.97,   "country": "DE"},
    "BEANR": {"name": "Port of Antwerp",      "lat": 51.22, "lon": 4.40,   "country": "BE"},
    "JPTYO": {"name": "Port of Tokyo",        "lat": 35.65, "lon": 139.75, "country": "JP"},
    "AEDXB": {"name": "Port of Dubai (Jebel Ali)", "lat": 24.98, "lon": 55.07, "country": "AE"},
    "CNNGB": {"name": "Port of Ningbo",       "lat": 29.87, "lon": 121.55, "country": "CN"},
}

# Congestion threshold: vessels waiting vs historical baseline
_CONGESTION_THRESHOLD = 1.5   # 50% above baseline triggers a signal
_HIGH_CONGESTION_THRESHOLD = 2.0  # 100% above = high severity


class AISSource(SignalSource):
    """Monitors vessel queues at major ports for early supply chain disruption signals.

    AIS data provides 48-72 hour lead time over traditional news coverage.
    This source requires a paid AIS data subscription (AISHub or MarineTraffic).
    """

    name = "ais_vessels"
    poll_interval = 3600  # hourly
    delay_hours = 0.0     # real-time advantage is the main value proposition

    def __init__(self) -> None:
        self._api_key: str | None = os.getenv("AIS_API_KEY")
        self._provider: str = os.getenv("AIS_PROVIDER", "aishub").lower()
        self._port_baselines: dict[str, int] = {}  # port_code → baseline vessel count

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def poll(self) -> list[Signal]:
        if not self.is_available():
            logger.debug("AIS: no API key configured (paid feature), skipping")
            return []
        signals: list[Signal] = []
        for port_code, port_info in _MONITORED_PORTS.items():
            try:
                vessel_count = await self._fetch_vessel_count(port_code, port_info)
                signal = self._evaluate_port(port_code, port_info, vessel_count)
                if signal:
                    signals.append(signal)
            except Exception as exc:
                logger.debug("AIS: failed to fetch %s: %s", port_code, exc)
        return signals

    async def _fetch_vessel_count(self, port_code: str, port_info: dict[str, Any]) -> int:
        """Fetch number of vessels anchored/waiting at port."""
        if self._provider == "aishub":
            return await self._fetch_aishub(port_info["lat"], port_info["lon"])
        return await self._fetch_marinetraffic(port_code)

    async def _fetch_aishub(self, lat: float, lon: float, radius_nm: float = 20) -> int:
        params = {
            "username": self._api_key,
            "format": "1",
            "output": "json",
            "latitudeMin": lat - 0.3,
            "latitudeMax": lat + 0.3,
            "longitudeMin": lon - 0.3,
            "longitudeMax": lon + 0.3,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get("https://data.aishub.net/ws.php", params=params)
            resp.raise_for_status()
        data = resp.json()
        # AISHub returns [{vessels: [...]}, {...]
        if isinstance(data, list) and len(data) > 1:
            vessels = data[1] if isinstance(data[1], list) else []
            # Count anchored/moored vessels (status 1=anchored, 5=moored)
            return sum(1 for v in vessels if v.get("NAVSTAT") in (1, 5))
        return 0

    async def _fetch_marinetraffic(self, port_code: str) -> int:
        params = {
            "v": "2",
            "protocol": "json",
            "msgtype": "vessels",
            "portid": port_code,
            "status": "0",  # anchored/waiting
        }
        async with httpx.AsyncClient(
            timeout=30,
            headers={"Authorization": f"Bearer {self._api_key}"},
        ) as client:
            resp = await client.get(
                "https://services.marinetraffic.com/api/exportvessel",
                params=params,
            )
            resp.raise_for_status()
        data = resp.json()
        return len(data.get("DATA", []))

    def _evaluate_port(
        self, port_code: str, port_info: dict[str, Any], vessel_count: int
    ) -> Signal | None:
        baseline = self._port_baselines.get(port_code)
        if baseline is None:
            self._port_baselines[port_code] = vessel_count
            return None  # establish baseline on first poll

        if baseline == 0:
            self._port_baselines[port_code] = max(vessel_count, 1)
            return None

        ratio = vessel_count / baseline
        if ratio < _CONGESTION_THRESHOLD:
            # Trend update — gradually update baseline
            self._port_baselines[port_code] = int(baseline * 0.95 + vessel_count * 0.05)
            return None

        severity = min(0.4 + (ratio - 1) * 0.3, 0.95)
        confidence = 0.85  # AIS data is objective physical observation

        return Signal(
            title=f"[AIS] Port congestion detected — {port_info['name']}",
            description=(
                f"{vessel_count} vessels anchored/waiting at {port_info['name']} "
                f"({ratio:.1f}× normal baseline of {baseline}). "
                "Potential supply chain disruption in 3-7 days."
            ),
            category="supply_chain",
            severity=round(severity, 3),
            confidence=confidence,
            source=self.name,
            source_url=f"https://www.marinetraffic.com/en/ais/details/ports/{port_code}",
            detected_at=datetime.now(timezone.utc),
            event_date=datetime.now(timezone.utc),
            affected_sectors=["supply_chain", "shipping", "retail"],
            affected_geographies=[port_info["country"]],
            keywords=["port congestion", "vessel queue", "shipping delay", port_info["name"].lower()],
        )
