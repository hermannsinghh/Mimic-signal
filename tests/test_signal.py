"""Tests for Signal and WeakSignal dataclasses."""

from datetime import datetime, timezone

import pytest

from mimic_signal.signal import Signal, WeakSignal


def test_signal_strength_geometric_mean():
    s = Signal(
        title="t", description="d", category="macro",
        severity=0.64, confidence=1.0,
        source="test", source_url="", detected_at=datetime.now(timezone.utc),
        event_date=datetime.now(timezone.utc),
    )
    assert abs(s.strength - 0.8) < 1e-6


def test_signal_strength_zero_confidence():
    s = Signal(
        title="t", description="d", category="macro",
        severity=0.9, confidence=0.0,
        source="test", source_url="", detected_at=datetime.now(timezone.utc),
        event_date=datetime.now(timezone.utc),
    )
    assert s.strength == 0.0


def test_signal_strength_both_half():
    s = Signal(
        title="t", description="d", category="macro",
        severity=0.5, confidence=0.5,
        source="test", source_url="", detected_at=datetime.now(timezone.utc),
        event_date=datetime.now(timezone.utc),
    )
    assert abs(s.strength - 0.5) < 1e-6


def test_signal_defaults():
    now = datetime.now(timezone.utc)
    s = Signal(
        title="t", description="d", category="geopolitical",
        severity=0.5, confidence=0.5,
        source="gdelt", source_url="http://example.com",
        detected_at=now, event_date=now,
    )
    assert s.affected_sectors == []
    assert s.affected_geographies == []
    assert s.keywords == []
    assert s.id  # auto-generated UUID


def test_signal_unique_ids():
    now = datetime.now(timezone.utc)
    kwargs = dict(
        title="t", description="d", category="macro",
        severity=0.5, confidence=0.5,
        source="test", source_url="",
        detected_at=now, event_date=now,
    )
    s1 = Signal(**kwargs)
    s2 = Signal(**kwargs)
    assert s1.id != s2.id


def test_signal_repr():
    now = datetime.now(timezone.utc)
    s = Signal(
        title="Port strike", description="d", category="supply_chain",
        severity=0.8, confidence=0.9,
        source="gdelt", source_url="",
        detected_at=now, event_date=now,
    )
    r = repr(s)
    assert "Port strike" in r
    assert "supply_chain" in r
    assert "0.80" in r


def test_weak_signal_lead_time_estimate():
    now = datetime.now(timezone.utc)
    ws = WeakSignal(
        pattern_name="bdi_decline_precedes_shipping_disruption",
        precedes="shipping disruption",
        title="t", description="d",
        signal_value=0.7, confidence=0.72,
        lead_time_min_days=14, lead_time_max_days=28,
        detected_at=now,
    )
    assert ws.lead_time_estimate == 21


def test_weak_signal_repr():
    now = datetime.now(timezone.utc)
    ws = WeakSignal(
        pattern_name="bdi_decline",
        precedes="shipping disruption",
        title="t", description="d",
        signal_value=0.6, confidence=0.7,
        lead_time_min_days=14, lead_time_max_days=28,
        detected_at=now,
    )
    r = repr(ws)
    assert "bdi_decline" in r
    assert "14-28d" in r
