"""GDELT 2.0 event feed — updated every 15 minutes, free, global coverage."""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from mimic_signal.signal import Signal
from mimic_signal.sources.base import SignalSource

logger = logging.getLogger(__name__)

_LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

# GDELT export CSV column indices (tab-separated, no header, 61 columns)
_COL = {
    "event_id": 0,
    "sql_date": 1,
    "event_code": 26,
    "event_base": 27,
    "event_root": 28,
    "quad_class": 29,    # 1=Verbal Coop, 2=Material Coop, 3=Verbal Conflict, 4=Material Conflict
    "goldstein": 30,     # -10 to +10
    "num_mentions": 31,
    "num_sources": 32,
    "num_articles": 33,
    "avg_tone": 34,      # -100 to +100
    "action_geo_name": 52,
    "action_geo_country": 53,
    "action_geo_lat": 56,
    "action_geo_lon": 57,
    "date_added": 59,
    "source_url": 60,
}

# CAMEO root codes → our signal categories
_CAMEO_CATEGORY: dict[str, str] = {
    "14": "labor",          # protest
    "15": "geopolitical",   # exhibit force
    "16": "supply_chain",   # reduce relations / sanctions
    "17": "supply_chain",   # coerce
    "18": "geopolitical",   # assault
    "19": "geopolitical",   # fight
    "20": "geopolitical",   # mass violence
    "06": "macro",          # material cooperation / economic aid
    "10": "macro",          # demand
    "11": "macro",          # disapprove
    "12": "macro",          # reject
    "13": "geopolitical",   # threaten
}

# Minimum article count to consider an event signal-worthy
_MIN_ARTICLES = 5
# Minimum absolute Goldstein scale for relevance
_MIN_GOLDSTEIN = 2.0


def _safe(row: list[str], idx: int, default: str = "") -> str:
    try:
        return row[idx].strip()
    except IndexError:
        return default


def _parse_row(row: list[str]) -> dict[str, Any] | None:
    if len(row) < 61:
        return None
    try:
        return {
            "event_id": _safe(row, _COL["event_id"]),
            "sql_date": _safe(row, _COL["sql_date"]),
            "event_code": _safe(row, _COL["event_code"]),
            "event_root": _safe(row, _COL["event_root"])[:2],
            "quad_class": int(_safe(row, _COL["quad_class"]) or "0"),
            "goldstein": float(_safe(row, _COL["goldstein"]) or "0"),
            "num_mentions": int(_safe(row, _COL["num_mentions"]) or "0"),
            "num_sources": int(_safe(row, _COL["num_sources"]) or "0"),
            "num_articles": int(_safe(row, _COL["num_articles"]) or "0"),
            "avg_tone": float(_safe(row, _COL["avg_tone"]) or "0"),
            "geo_name": _safe(row, _COL["action_geo_name"]),
            "geo_country": _safe(row, _COL["action_geo_country"]),
            "source_url": _safe(row, _COL["source_url"]),
            "date_added": _safe(row, _COL["date_added"]),
        }
    except (ValueError, TypeError):
        return None


def _is_relevant(ev: dict[str, Any]) -> bool:
    if ev["num_articles"] < _MIN_ARTICLES:
        return False
    if abs(ev["goldstein"]) < _MIN_GOLDSTEIN and ev["quad_class"] < 3:
        return False
    # High-conflict events
    if ev["quad_class"] == 4 and ev["avg_tone"] < -2:
        return True
    # Sanctions / coercion
    if ev["event_root"] in ("16", "17") and abs(ev["goldstein"]) >= 3:
        return True
    # High mention volume with negative tone
    if ev["num_mentions"] >= 30 and ev["avg_tone"] < -3:
        return True
    return False


def _severity(ev: dict[str, Any]) -> float:
    base = abs(ev["goldstein"]) / 10.0
    conflict_boost = 0.1 if ev["quad_class"] == 4 else 0.0
    tone_boost = 0.1 if ev["avg_tone"] < -5 else 0.0
    return min(base + conflict_boost + tone_boost, 1.0)


def _confidence(ev: dict[str, Any]) -> float:
    src = min(ev["num_sources"] / 10.0, 1.0) * 0.7
    art = min(ev["num_articles"] / 50.0, 1.0) * 0.3
    return round(src + art, 3)


def _category(ev: dict[str, Any]) -> str:
    return _CAMEO_CATEGORY.get(ev["event_root"], "geopolitical")


def _event_date(sql_date: str) -> datetime:
    try:
        return datetime.strptime(sql_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _keywords(ev: dict[str, Any]) -> list[str]:
    kw = []
    if ev["geo_name"]:
        kw += [w.lower() for w in ev["geo_name"].split(",") if w.strip()]
    if ev["geo_country"]:
        kw.append(ev["geo_country"].lower())
    code = ev["event_code"]
    if code.startswith("16"):
        kw += ["sanctions", "embargo", "trade restriction"]
    elif code.startswith("14"):
        kw += ["protest", "strike", "labor"]
    elif ev["quad_class"] == 4:
        kw += ["conflict", "violence"]
    return list(dict.fromkeys(kw))  # dedupe, preserve order


class GDELTSource(SignalSource):
    """Polls GDELT 2.0 15-minute event export for high-severity global events."""

    name = "gdelt"
    poll_interval = 900  # 15 minutes
    delay_hours = 24.0

    def __init__(self) -> None:
        self._last_export_url: str | None = None
        self._seen: set[str] = set()

    def is_available(self) -> bool:
        return True  # GDELT is public, no credentials needed

    async def poll(self) -> list[Signal]:
        try:
            export_url = await self._fetch_export_url()
        except Exception as exc:
            logger.warning("GDELT: could not fetch lastupdate.txt: %s", exc)
            return []

        if export_url == self._last_export_url:
            return []  # no new file since last poll

        try:
            events = await self._download_events(export_url)
        except Exception as exc:
            logger.warning("GDELT: could not download %s: %s", export_url, exc)
            return []

        self._last_export_url = export_url
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.delay_hours)
        signals: list[Signal] = []

        for ev in events:
            if ev["event_id"] in self._seen:
                continue
            if not _is_relevant(ev):
                continue

            ev_date = _event_date(ev["sql_date"])
            if ev_date > cutoff:
                continue  # not old enough for open-source tier

            self._seen.add(ev["event_id"])
            signals.append(
                Signal(
                    title=self._make_title(ev),
                    description=self._make_description(ev),
                    category=_category(ev),
                    severity=round(_severity(ev), 3),
                    confidence=_confidence(ev),
                    source=self.name,
                    source_url=ev["source_url"],
                    detected_at=datetime.now(timezone.utc),
                    event_date=ev_date,
                    affected_sectors=self._infer_sectors(ev),
                    affected_geographies=[ev["geo_country"]] if ev["geo_country"] else [],
                    keywords=_keywords(ev),
                )
            )

        # Trim seen set to avoid unbounded growth
        if len(self._seen) > 50_000:
            self._seen = set(list(self._seen)[-25_000:])

        logger.info("GDELT: %d signals from %s", len(signals), export_url)
        return signals

    async def _fetch_export_url(self) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_LASTUPDATE_URL)
            resp.raise_for_status()
        parts = resp.text.strip().split()
        urls = [p for p in parts if "export.CSV" in p]
        if not urls:
            raise ValueError(f"No export URL found in: {resp.text[:200]!r}")
        return urls[0]

    async def _download_events(self, url: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as f:
                content = f.read().decode("utf-8", errors="replace")

        events = []
        reader = csv.reader(io.StringIO(content), delimiter="\t")
        for row in reader:
            parsed = _parse_row(row)
            if parsed is not None:
                events.append(parsed)
        return events

    def _make_title(self, ev: dict[str, Any]) -> str:
        category = _category(ev)
        geo = ev["geo_name"].split(",")[0] if ev["geo_name"] else "Global"
        return f"[GDELT] {category.replace('_', ' ').title()} event detected — {geo}"

    def _make_description(self, ev: dict[str, Any]) -> str:
        return (
            f"CAMEO code {ev['event_code']} | QuadClass {ev['quad_class']} | "
            f"Goldstein {ev['goldstein']:+.1f} | Tone {ev['avg_tone']:.1f} | "
            f"{ev['num_articles']} articles across {ev['num_sources']} sources"
        )

    def _infer_sectors(self, ev: dict[str, Any]) -> list[str]:
        sectors: list[str] = []
        root = ev["event_root"]
        if root in ("16", "17"):
            sectors.append("supply_chain")
        if root in ("18", "19", "20"):
            sectors += ["energy", "manufacturing"]
        if root == "14":
            sectors.append("labor")
        return sectors or ["general"]
