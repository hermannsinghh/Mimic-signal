"""Shared test fixtures."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mimic_signal.signal import Signal


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def make_signal(now):
    def _make(
        title="Test supply chain event",
        description="Port of Shanghai congestion increasing",
        category="supply_chain",
        severity=0.7,
        confidence=0.8,
        source="gdelt",
        source_url="https://example.com/event",
        sectors=None,
        geographies=None,
        keywords=None,
    ) -> Signal:
        return Signal(
            title=title,
            description=description,
            category=category,
            severity=severity,
            confidence=confidence,
            source=source,
            source_url=source_url,
            detected_at=now,
            event_date=now,
            affected_sectors=sectors or ["supply_chain"],
            affected_geographies=geographies or ["CN"],
            keywords=keywords or ["shanghai", "port", "congestion"],
        )
    return _make
