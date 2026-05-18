"""Tests for SignalMonitor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mimic_signal.monitor import SignalMonitor
from mimic_signal.signal import Signal


def _make_signal(title="Test event", severity=0.7, confidence=0.8, category="supply_chain"):
    now = datetime.now(timezone.utc)
    return Signal(
        title=title, description="test description",
        category=category, severity=severity, confidence=confidence,
        source="gdelt", source_url="http://example.com",
        detected_at=now, event_date=now,
        affected_sectors=["supply_chain"],
        affected_geographies=["CN"],
        keywords=["test"],
    )


def test_monitor_construction():
    m = SignalMonitor(threshold=0.6)
    assert m.threshold == 0.6
    assert m.twins == []
    assert m.world is None


def test_watch_configures_sources():
    m = SignalMonitor()
    m.watch(["gdelt", "sec_8k"])
    assert len(m._sources) == 2
    assert m._sources[0].name == "gdelt"
    assert m._sources[1].name == "sec_8k"


def test_watch_unknown_source_raises():
    m = SignalMonitor()
    with pytest.raises(ValueError, match="Unknown source"):
        m.watch(["nonexistent_source"])


def test_on_signal_decorator_registers_handler():
    m = SignalMonitor(threshold=0.5)
    called = []

    @m.on_signal(threshold=0.6)
    def handler(signal, affected):
        called.append(signal)

    assert len(m._handlers) == 1
    assert m._handlers[0][1] == 0.6


def test_on_signal_uses_monitor_threshold_when_none():
    m = SignalMonitor(threshold=0.55)

    @m.on_signal()
    def handler(signal, affected):
        pass

    assert m._handlers[0][1] == 0.55


def test_recent_signals_empty():
    m = SignalMonitor()
    assert m.recent_signals() == []


def test_signal_log_empty():
    m = SignalMonitor()
    df = m.signal_log()
    assert len(df) == 0


@pytest.mark.asyncio
async def test_process_fires_handler_above_threshold():
    m = SignalMonitor(threshold=0.5)
    fired = []

    @m.on_signal(threshold=0.5)
    def handler(signal, affected):
        fired.append(signal)

    sig = _make_signal(severity=0.8, confidence=0.9)
    await m._process([sig])
    assert len(fired) == 1


@pytest.mark.asyncio
async def test_process_does_not_fire_below_threshold():
    m = SignalMonitor(threshold=0.5)
    fired = []

    @m.on_signal(threshold=0.8)
    def handler(signal, affected):
        fired.append(signal)

    sig = _make_signal(severity=0.4, confidence=0.4)  # strength = 0.4
    await m._process([sig])
    assert fired == []


@pytest.mark.asyncio
async def test_process_deduplicates():
    m = SignalMonitor(threshold=0.0)
    fired = []

    @m.on_signal()
    def handler(signal, affected):
        fired.append(signal)

    sig1 = _make_signal(title="Port closure at Shanghai")
    sig2 = _make_signal(title="Port closure at Shanghai")  # duplicate
    await m._process([sig1, sig2])
    assert len(fired) == 1


@pytest.mark.asyncio
async def test_process_adds_to_history():
    m = SignalMonitor(threshold=0.0)
    sig = _make_signal()
    await m._process([sig])
    assert len(m._signal_history) == 1


@pytest.mark.asyncio
async def test_process_handler_error_does_not_stop():
    m = SignalMonitor(threshold=0.0)

    @m.on_signal()
    def bad_handler(signal, affected):
        raise RuntimeError("handler crash")

    sig = _make_signal()
    # Should not raise
    await m._process([sig])


@pytest.mark.asyncio
async def test_process_async_handler():
    m = SignalMonitor(threshold=0.0)
    fired = []

    @m.on_signal()
    async def async_handler(signal, affected):
        fired.append(signal)

    sig = _make_signal()
    await m._process([sig])
    assert len(fired) == 1


def test_signal_log_returns_dataframe():
    m = SignalMonitor(threshold=0.0)
    now = datetime.now(timezone.utc)
    m._signal_history.append(_make_signal())
    df = m.signal_log()
    assert len(df) == 1
    assert "strength" in df.columns
    assert "category" in df.columns


@pytest.mark.asyncio
async def test_start_async_stops_on_cancel():
    m = SignalMonitor()
    m.watch(["gdelt"])

    # Mock the source to block
    m._sources[0].poll = AsyncMock(return_value=[])
    m._sources[0].poll_interval = 0.01

    task = m.start_async()
    await asyncio.sleep(0.05)
    m.stop()
    await asyncio.sleep(0.05)
    assert not m._running


@pytest.mark.asyncio
async def test_twin_relevance_matching():
    twin = MagicMock()
    twin.ticker = "WMT"
    twin.sector = "consumer discretionary"
    twin.geographies = ["US", "CN"]

    m = SignalMonitor(twins=[twin], threshold=0.0)
    fired_affected = []

    @m.on_signal()
    def handler(signal, affected):
        fired_affected.append(affected)

    sig = _make_signal(category="supply_chain")
    sig.affected_sectors = ["supply_chain"]
    sig.affected_geographies = ["CN"]
    await m._process([sig])

    assert len(fired_affected) == 1
    assert twin in fired_affected[0]
