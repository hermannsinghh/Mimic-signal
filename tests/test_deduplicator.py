"""Tests for the Deduplicator."""

from datetime import datetime, timezone

import pytest

from mimic_signal.deduplicator import Deduplicator
from mimic_signal.signal import Signal


def _sig(title, description, category="supply_chain"):
    now = datetime.now(timezone.utc)
    return Signal(
        title=title, description=description,
        category=category, severity=0.7, confidence=0.8,
        source="gdelt", source_url="",
        detected_at=now, event_date=now,
    )


def test_new_signal_not_duplicate():
    d = Deduplicator()
    s = _sig("Port of Shanghai strike", "Workers strike at major port")
    assert not d.is_duplicate(s)


def test_same_signal_is_duplicate_after_add():
    d = Deduplicator()
    s = _sig("Port of Shanghai strike", "Workers strike at major port")
    d.add(s)
    s2 = _sig("Port of Shanghai strike", "Workers strike at major port again")
    assert d.is_duplicate(s2)


def test_different_signals_not_duplicate():
    d = Deduplicator()
    s1 = _sig("Port of Shanghai strike", "Workers strike at major port")
    s2 = _sig("FOMC rate hike announced", "Federal Reserve raises rates by 50bps")
    d.add(s1)
    assert not d.is_duplicate(s2)


def test_different_category_not_duplicate():
    d = Deduplicator()
    s1 = _sig("Supply chain disruption event", "Port congestion causing delays", "supply_chain")
    s2 = _sig("Supply chain disruption event", "Port congestion causing delays", "macro")
    d.add(s1)
    assert not d.is_duplicate(s2)


def test_add_and_check_multiple():
    d = Deduplicator()
    signals = [
        _sig("Port closure", "Shanghai port closed due to typhoon"),
        _sig("Rate hike", "Fed raises rates by 25bps macro shock"),
        _sig("Sanctions imposed", "New sanctions against energy sector geopolitical"),
    ]
    for s in signals:
        d.add(s)

    dup = _sig("Port closed", "Shanghai port typhoon closure again")
    assert d.is_duplicate(dup)

    unique = _sig("Earnings miss", "Company reports poor quarterly results")
    assert not d.is_duplicate(unique)


def test_high_threshold_allows_similar():
    d = Deduplicator(threshold=0.99)
    s1 = _sig("Port shutdown", "Port closed for workers")
    s2 = _sig("Harbor closed", "Dock workers strike began yesterday")
    d.add(s1)
    assert not d.is_duplicate(s2)


def test_low_threshold_deduplicates_similar():
    d = Deduplicator(threshold=0.10)
    s1 = _sig("Port disruption", "Shanghai port facing major disruption due to worker strike")
    s2 = _sig("Shanghai port strike", "Major disruption at port due to strike workers")
    d.add(s1)
    assert d.is_duplicate(s2)
