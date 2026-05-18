"""Tests for the SEC 8-K source adapter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mimic_signal.sources.sec_8k import SEC8KSource, _extract_items, _max_severity, _parse_entry


def _make_entry(title="8-K - APPLE INC (0000320193) (Filer)",
                summary="Filed: 2024-01-15 AccNo: 0000320193-24-000001 Item 2.06",
                link="https://www.sec.gov/filing/1",
                updated="2024-01-15T09:30:00-05:00"):
    return SimpleNamespace(title=title, summary=summary, link=link, updated=updated)


def test_extract_items_from_summary():
    items = _extract_items("Item 1.01 agreement signed. Item 2.06 impairment recorded.")
    assert "1.01" in items
    assert "2.06" in items


def test_extract_items_case_insensitive():
    items = _extract_items("item 1.03 bankruptcy")
    assert "1.03" in items


def test_extract_items_empty():
    items = _extract_items("no items here")
    assert items == []


def test_max_severity_bankruptcy():
    severity, desc, sectors = _max_severity(["1.03"])
    assert severity >= 0.95
    assert "Bankruptcy" in desc


def test_max_severity_multiple_takes_highest():
    severity, desc, _ = _max_severity(["5.02", "2.06"])
    assert severity >= 0.85  # 2.06 wins over 5.02


def test_max_severity_unknown_item():
    severity, _, _ = _max_severity(["9.99"])
    assert severity == 0.40  # default


def test_parse_entry_extracts_company():
    entry = _make_entry()
    result = _parse_entry(entry)
    assert result is not None
    assert result["company"] == "APPLE INC"
    assert result["cik"] == "0000320193"


def test_parse_entry_extracts_items():
    entry = _make_entry(summary="Filed: 2024-01-15 Item 2.06 impairment disclosure")
    result = _parse_entry(entry)
    assert "2.06" in result["items"]


def test_parse_entry_bad_input():
    result = _parse_entry(SimpleNamespace())  # missing attributes
    # Should not raise, may return None or partial result
    # The key is it doesn't crash


@pytest.mark.asyncio
async def test_poll_returns_signals():
    source = SEC8KSource()
    source.delay_hours = 0.0

    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    entries = [
        _make_entry(
            title="8-K - WALMART INC (0000104169) (Filer)",
            summary="Item 2.06 Material Impairment disclosure",
            link="https://sec.gov/filing/walmart-1",
            updated=old_time,
        )
    ]

    with patch.object(source, "_fetch_feed", new=AsyncMock(return_value=entries)):
        signals = await source.poll()

    assert len(signals) == 1
    assert "WALMART" in signals[0].title
    assert signals[0].severity >= 0.85
    assert signals[0].confidence == 0.90


@pytest.mark.asyncio
async def test_poll_deduplicates_by_link():
    source = SEC8KSource()
    source.delay_hours = 0.0

    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    entries = [_make_entry(link="https://sec.gov/filing/unique-1", updated=old_time)]

    with patch.object(source, "_fetch_feed", new=AsyncMock(return_value=entries)):
        s1 = await source.poll()
        s2 = await source.poll()

    assert len(s1) == 1
    assert len(s2) == 0


@pytest.mark.asyncio
async def test_poll_skips_too_recent():
    source = SEC8KSource()
    source.delay_hours = 1.0

    now = datetime.now(timezone.utc).isoformat()
    entries = [_make_entry(updated=now)]

    with patch.object(source, "_fetch_feed", new=AsyncMock(return_value=entries)):
        signals = await source.poll()

    assert signals == []


@pytest.mark.asyncio
async def test_poll_handles_error():
    source = SEC8KSource()
    with patch.object(source, "_fetch_feed", new=AsyncMock(side_effect=Exception("network error"))):
        signals = await source.poll()
    assert signals == []
