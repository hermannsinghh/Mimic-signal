"""Tests for the GDELT source adapter."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mimic_signal.sources.gdelt import GDELTSource, _parse_row, _is_relevant, _severity, _confidence


def _make_row(**kwargs) -> list[str]:
    """Build a 61-column GDELT row with defaults."""
    defaults = {
        "event_id": "123456",
        "sql_date": (datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y%m%d"),
        "event_code": "1621",
        "event_root": "16",
        "quad_class": "4",
        "goldstein": "-7.0",
        "num_mentions": "50",
        "num_sources": "8",
        "num_articles": "25",
        "avg_tone": "-6.5",
        "geo_name": "Shanghai, China",
        "geo_country": "CN",
        "source_url": "https://example.com/article",
    }
    defaults.update(kwargs)
    row = [""] * 61
    from mimic_signal.sources.gdelt import _COL
    row[_COL["event_id"]] = defaults["event_id"]
    row[_COL["sql_date"]] = defaults["sql_date"]
    row[_COL["event_code"]] = defaults["event_code"]
    row[_COL["event_base"]] = defaults["event_code"]
    row[_COL["event_root"]] = defaults["event_root"]
    row[_COL["quad_class"]] = defaults["quad_class"]
    row[_COL["goldstein"]] = defaults["goldstein"]
    row[_COL["num_mentions"]] = defaults["num_mentions"]
    row[_COL["num_sources"]] = defaults["num_sources"]
    row[_COL["num_articles"]] = defaults["num_articles"]
    row[_COL["avg_tone"]] = defaults["avg_tone"]
    row[_COL["action_geo_name"]] = defaults["geo_name"]
    row[_COL["action_geo_country"]] = defaults["geo_country"]
    row[_COL["source_url"]] = defaults["source_url"]
    return row


def _make_zip(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t")
    for row in rows:
        writer.writerow(row)
    content = buf.getvalue().encode()
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("events.csv", content)
    return zip_buf.getvalue()


def test_parse_row_valid():
    row = _make_row()
    result = _parse_row(row)
    assert result is not None
    assert result["event_id"] == "123456"
    assert result["quad_class"] == 4
    assert result["goldstein"] == -7.0
    assert result["num_articles"] == 25


def test_parse_row_too_short():
    assert _parse_row(["a", "b"]) is None


def test_is_relevant_high_conflict():
    ev = {
        "num_articles": 25, "quad_class": 4, "goldstein": -7.0,
        "avg_tone": -6.5, "event_root": "16", "num_mentions": 50,
    }
    assert _is_relevant(ev)


def test_is_relevant_too_few_articles():
    ev = {
        "num_articles": 2, "quad_class": 4, "goldstein": -8.0,
        "avg_tone": -6.0, "event_root": "16", "num_mentions": 5,
    }
    assert not _is_relevant(ev)


def test_severity_computation():
    ev = {"goldstein": -8.0, "quad_class": 4, "avg_tone": -7.0}
    s = _severity(ev)
    assert 0.7 < s <= 1.0


def test_confidence_from_sources():
    ev = {"num_sources": 10, "num_articles": 50}
    c = _confidence(ev)
    assert c >= 0.95


def test_confidence_low_sources():
    ev = {"num_sources": 1, "num_articles": 3}
    c = _confidence(ev)
    assert c < 0.30


@pytest.mark.asyncio
async def test_poll_returns_signals():
    source = GDELTSource()
    source.delay_hours = 0.0  # disable delay for test

    old_date = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y%m%d")
    rows = [_make_row(sql_date=old_date)]
    zip_data = _make_zip(rows)

    with (
        patch.object(source, "_fetch_export_url", new=AsyncMock(return_value="http://example.com/test.zip")),
        patch.object(source, "_download_events", new=AsyncMock(return_value=[_parse_row(_make_row(sql_date=old_date))])),
    ):
        signals = await source.poll()

    assert len(signals) == 1
    assert signals[0].source == "gdelt"
    assert signals[0].severity > 0


@pytest.mark.asyncio
async def test_poll_deduplicates_seen_events():
    source = GDELTSource()
    source.delay_hours = 0.0

    old_date = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y%m%d")
    event = _parse_row(_make_row(sql_date=old_date))

    with (
        patch.object(source, "_fetch_export_url", new=AsyncMock(side_effect=["url1", "url2"])),
        patch.object(source, "_download_events", new=AsyncMock(return_value=[event])),
    ):
        signals1 = await source.poll()
        signals2 = await source.poll()

    assert len(signals1) == 1
    assert len(signals2) == 0  # same event_id seen already


@pytest.mark.asyncio
async def test_poll_skips_too_recent():
    source = GDELTSource()
    source.delay_hours = 24.0  # enforce delay

    # Event from today — should be filtered out by delay
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    event = _parse_row(_make_row(sql_date=today))
    event["event_id"] = "fresh_event"

    with (
        patch.object(source, "_fetch_export_url", new=AsyncMock(return_value="http://example.com/new.zip")),
        patch.object(source, "_download_events", new=AsyncMock(return_value=[event])),
    ):
        signals = await source.poll()

    assert signals == []


@pytest.mark.asyncio
async def test_poll_handles_network_error():
    source = GDELTSource()
    with patch.object(source, "_fetch_export_url", new=AsyncMock(side_effect=Exception("timeout"))):
        signals = await source.poll()
    assert signals == []


def test_is_available():
    assert GDELTSource().is_available()
