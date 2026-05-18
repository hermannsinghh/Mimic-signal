"""Tests for the SignalScorer."""

from datetime import datetime, timezone

import pytest

from mimic_signal.scorer import SignalScorer
from mimic_signal.signal import Signal


def _make(severity=0.5, confidence=0.5, sectors=None, keywords=None, title="test", description="test desc"):
    now = datetime.now(timezone.utc)
    return Signal(
        title=title, description=description, category="macro",
        severity=severity, confidence=confidence,
        source="test", source_url="",
        detected_at=now, event_date=now,
        affected_sectors=sectors or [],
        keywords=keywords or [],
    )


def test_scorer_clamps_severity():
    scorer = SignalScorer()
    s = _make(severity=1.5, confidence=0.8)
    result = scorer.score(s)
    assert result.severity == 1.0


def test_scorer_clamps_confidence():
    scorer = SignalScorer()
    s = _make(severity=0.5, confidence=-0.3)
    result = scorer.score(s)
    assert result.confidence == 0.0


def test_scorer_infers_sectors_from_title():
    scorer = SignalScorer()
    s = _make(title="Port congestion at Shanghai", description="shipping delayed", sectors=[])
    result = scorer.score(s)
    assert "supply_chain" in result.affected_sectors


def test_scorer_infers_sectors_from_description():
    scorer = SignalScorer()
    s = _make(description="semiconductor chip shortage affecting production", sectors=[])
    result = scorer.score(s)
    assert "technology" in result.affected_sectors


def test_scorer_does_not_overwrite_existing_sectors():
    scorer = SignalScorer()
    s = _make(sectors=["energy"], title="oil prices rising")
    result = scorer.score(s)
    assert result.affected_sectors == ["energy"]


def test_scorer_fills_keywords_when_empty():
    scorer = SignalScorer()
    s = _make(title="Port shutdown Shanghai", description="container ship blocked", keywords=[])
    result = scorer.score(s)
    assert len(result.keywords) > 0


def test_scorer_does_not_overwrite_existing_keywords():
    scorer = SignalScorer()
    s = _make(keywords=["mykey"])
    result = scorer.score(s)
    assert "mykey" in result.keywords


def test_scorer_general_fallback():
    scorer = SignalScorer()
    s = _make(title="something happened somewhere", description="vague event", sectors=[])
    result = scorer.score(s)
    assert result.affected_sectors == ["general"]
