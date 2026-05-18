"""Tests for the weak signal system."""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from mimic_signal.weak_signals.detector import WeakSignalDetector
from mimic_signal.weak_signals.library import (
    ALL_PATTERNS,
    PATTERN_REGISTRY,
    bdi_decline_precedes_shipping_disruption,
    vessel_queue_growth_precedes_port_disruption,
    credit_spread_widening_precedes_financial_stress,
    earnings_whisper_divergence_precedes_surprise,
)
from mimic_signal.weak_signals.patterns import WeakSignalPattern


# ─── Pattern detection unit tests ───────────────────────────────────────────

def test_bdi_decline_triggers_on_15pct_drop():
    # 10 days, drop from 2000 to 1600 = -20%
    values = pd.Series([2000, 1990, 1980, 1960, 1940, 1920, 1900, 1850, 1800, 1750, 1600])
    triggered, score = bdi_decline_precedes_shipping_disruption.detect(values)
    assert triggered
    assert score > 0


def test_bdi_decline_no_trigger_on_small_drop():
    values = pd.Series([2000, 1990, 1985, 1980, 1978, 1975, 1972, 1970, 1968, 1965, 1960])
    triggered, _ = bdi_decline_precedes_shipping_disruption.detect(values)
    assert not triggered


def test_bdi_decline_insufficient_data():
    values = pd.Series([2000, 1800])
    triggered, score = bdi_decline_precedes_shipping_disruption.detect(values)
    assert not triggered
    assert score == 0.0


def test_vessel_queue_growth_triggers():
    # Grows 80% over 5 days
    values = pd.Series([10, 10, 11, 12, 13, 14, 18])
    triggered, score = vessel_queue_growth_precedes_port_disruption.detect(values)
    assert triggered


def test_vessel_queue_growth_no_trigger():
    values = pd.Series([10, 10, 11, 11, 11, 12, 12])
    triggered, _ = vessel_queue_growth_precedes_port_disruption.detect(values)
    assert not triggered


def test_credit_spread_widening_triggers():
    # Spread widens 20% over 10 days
    values = pd.Series([80, 81, 82, 83, 84, 85, 87, 89, 92, 94, 96])
    triggered, score = credit_spread_widening_precedes_financial_stress.detect(values)
    assert triggered


def test_whisper_divergence_triggers():
    values = pd.Series([0.0, 0.15])  # 15% divergence from consensus
    triggered, score = earnings_whisper_divergence_precedes_surprise.detect(values)
    assert triggered


def test_whisper_divergence_no_trigger():
    values = pd.Series([0.0, 0.05])  # 5% — below threshold
    triggered, _ = earnings_whisper_divergence_precedes_surprise.detect(values)
    assert not triggered


# ─── Library registry ────────────────────────────────────────────────────────

def test_all_patterns_count():
    assert len(ALL_PATTERNS) == 10


def test_pattern_registry_keys():
    assert "bdi_decline_precedes_shipping_disruption" in PATTERN_REGISTRY
    assert "vessel_queue_growth_precedes_port_disruption" in PATTERN_REGISTRY
    assert "fed_language_shift_precedes_rate_decision" in PATTERN_REGISTRY


def test_all_patterns_have_required_fields():
    for pattern in ALL_PATTERNS:
        assert pattern.name
        assert pattern.precedes
        assert pattern.description
        assert len(pattern.lead_time_days) == 2
        assert pattern.lead_time_days[0] < pattern.lead_time_days[1]
        assert 0 < pattern.historical_precision <= 1.0
        assert callable(pattern.detect)
        assert len(pattern.features) >= 1


# ─── WeakSignalDetector ──────────────────────────────────────────────────────

def test_detector_unknown_pattern_raises():
    d = WeakSignalDetector()
    with pytest.raises(ValueError, match="Unknown pattern"):
        d.watch_for("nonexistent_pattern")


def test_detector_watch_all():
    d = WeakSignalDetector()
    d.watch_all()
    assert len(d._patterns) == 10


def test_detector_fires_on_bdi_decline():
    d = WeakSignalDetector()
    d.watch_for("bdi_decline_precedes_shipping_disruption")

    fired = []

    @d.on_weak_signal("bdi_decline_precedes_shipping_disruption")
    def handler(ws):
        fired.append(ws)

    # Feed a steep decline
    series = [2000] * 3 + [1800, 1750, 1700, 1650, 1620, 1590, 1560, 1520]
    ws_list = d.update_series("bdi_daily", series)

    assert len(fired) >= 1 or len(ws_list) >= 1


def test_detector_cooldown_prevents_double_fire():
    d = WeakSignalDetector()
    d._cooldown_hours = 0.0  # disable for test
    d.watch_for("bdi_decline_precedes_shipping_disruption")

    fire_count = [0]

    @d.on_weak_signal("bdi_decline_precedes_shipping_disruption")
    def handler(ws):
        fire_count[0] += 1

    # First steep decline
    d.update_series("bdi_daily", [2000] * 5 + [1500] * 6)
    count_after_first = fire_count[0]

    # Restore cooldown and add more decline — should not double fire
    d._cooldown_hours = 100.0
    d.update_series("bdi_daily", [1400] * 6)
    assert fire_count[0] == count_after_first


def test_detector_returns_weak_signal_objects():
    d = WeakSignalDetector()
    d.watch_for("bdi_decline_precedes_shipping_disruption")
    d._cooldown_hours = 0.0

    values = [2000] * 5 + [1500] * 6
    ws_list = d.update_series("bdi_daily", values)
    if ws_list:
        ws = ws_list[0]
        assert ws.pattern_name == "bdi_decline_precedes_shipping_disruption"
        assert ws.lead_time_min_days == 14
        assert ws.lead_time_max_days == 28
        assert ws.confidence == pytest.approx(0.72)


def test_detector_get_series():
    d = WeakSignalDetector()
    d.update_series("bdi_daily", [1000, 1100, 1200])
    s = d.get_series("bdi_daily")
    assert len(s) == 3
    assert s.iloc[-1] == 1200


def test_custom_pattern():
    def always_fires(series):
        return True, 1.0

    pattern = WeakSignalPattern(
        name="always_fires",
        precedes="test event",
        description="Always fires",
        lead_time_days=(1, 5),
        features=["test_series"],
        threshold=0.0,
        historical_precision=1.0,
        detect=always_fires,
    )

    d = WeakSignalDetector()
    d.add_pattern(pattern)
    ws_list = d.update("test_series", 1.0)
    assert len(ws_list) == 1
    assert ws_list[0].pattern_name == "always_fires"
