"""SEC EDGAR real-time 8-K feed — material event filings from US public companies."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx

from mimic_signal.signal import Signal
from mimic_signal.sources.base import SignalSource

logger = logging.getLogger(__name__)

_FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&dateb=&owner=include&count=40&search_text=&output=atom"
)

# Item numbers → (severity, description, sectors)
_ITEM_SEVERITY: dict[str, tuple[float, str, list[str]]] = {
    "1.03": (0.95, "Bankruptcy or Receivership", ["finance"]),
    "4.02": (0.90, "Non-Reliance on Previously Issued Financial Statements", ["finance"]),
    "2.06": (0.85, "Material Impairment", ["finance"]),
    "2.01": (0.75, "Completion of Acquisition or Disposition", ["finance", "strategy"]),
    "2.02": (0.65, "Results of Operations and Financial Condition", ["finance"]),
    "1.01": (0.60, "Entry into Material Definitive Agreement", ["finance", "strategy"]),
    "1.02": (0.65, "Termination of Material Definitive Agreement", ["finance"]),
    "5.02": (0.55, "Departure or Appointment of Principal Officer", ["governance"]),
    "7.01": (0.45, "Regulation FD Disclosure", ["finance"]),
    "8.01": (0.50, "Other Events", ["general"]),
}

_ITEM_RE = re.compile(r"Item\s+(\d+\.\d+)", re.IGNORECASE)


def _extract_items(text: str) -> list[str]:
    return _ITEM_RE.findall(text)


def _parse_entry(entry: Any) -> dict[str, Any] | None:
    try:
        title: str = getattr(entry, "title", "") or ""
        summary: str = getattr(entry, "summary", "") or ""
        link: str = getattr(entry, "link", "") or ""
        updated: str = getattr(entry, "updated", "") or ""

        # Extract company name from title: "8-K - COMPANY NAME (CIK)"
        company = ""
        cik = ""
        m = re.match(r"8-K\s+-\s+(.+?)\s*\((\d+)\)", title)
        if m:
            company = m.group(1).strip()
            cik = m.group(2)

        items = _extract_items(summary) or _extract_items(title)

        filed_at: datetime | None = None
        if updated:
            try:
                from dateutil import parser as dp
                filed_at = dp.parse(updated)
                if filed_at.tzinfo is None:
                    filed_at = filed_at.replace(tzinfo=timezone.utc)
            except Exception:
                filed_at = datetime.now(timezone.utc)

        return {
            "company": company,
            "cik": cik,
            "items": items,
            "link": link,
            "filed_at": filed_at or datetime.now(timezone.utc),
            "summary": summary[:500],
        }
    except Exception:
        return None


def _max_severity(items: list[str]) -> tuple[float, str, list[str]]:
    best = (0.40, "SEC 8-K Filing", ["general"])
    for item in items:
        severity, desc, sectors = _ITEM_SEVERITY.get(item, (0.40, "SEC 8-K Filing", ["general"]))
        if severity > best[0]:
            best = (severity, desc, sectors)
    return best


class SEC8KSource(SignalSource):
    """Polls the SEC EDGAR real-time 8-K RSS feed for material events."""

    name = "sec_8k"
    poll_interval = 300  # check every 5 minutes
    delay_hours = 1.0

    def __init__(self) -> None:
        self._seen_links: set[str] = set()

    def is_available(self) -> bool:
        return True  # SEC EDGAR is public

    async def poll(self) -> list[Signal]:
        try:
            entries = await self._fetch_feed()
        except Exception as exc:
            logger.warning("SEC 8-K: feed fetch failed: %s", exc)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.delay_hours)
        signals: list[Signal] = []

        for raw in entries:
            entry = _parse_entry(raw)
            if entry is None:
                continue
            if entry["link"] in self._seen_links:
                continue
            if entry["filed_at"] > cutoff:
                continue  # too recent for open-source tier

            self._seen_links.add(entry["link"])
            severity, item_desc, sectors = _max_severity(entry["items"])
            items_str = ", ".join(f"Item {i}" for i in entry["items"]) if entry["items"] else "unspecified"
            company = entry["company"] or "Unknown Company"

            signals.append(
                Signal(
                    title=f"[SEC 8-K] {company} — {item_desc}",
                    description=(
                        f"{company} filed an 8-K disclosing: {item_desc}. "
                        f"Items reported: {items_str}. "
                        f"Filed: {entry['filed_at'].strftime('%Y-%m-%d %H:%M UTC')}"
                    ),
                    category="company_event",
                    severity=severity,
                    confidence=0.90,  # self-reported by company — high confidence
                    source=self.name,
                    source_url=entry["link"],
                    detected_at=datetime.now(timezone.utc),
                    event_date=entry["filed_at"],
                    affected_sectors=sectors,
                    affected_geographies=["US"],
                    keywords=[company.lower()] + [f"item {i}" for i in entry["items"]],
                )
            )

        if len(self._seen_links) > 10_000:
            self._seen_links = set(list(self._seen_links)[-5_000:])

        logger.info("SEC 8-K: %d new signals", len(signals))
        return signals

    async def _fetch_feed(self) -> list[Any]:
        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": "mimic-signal/0.1 research@example.com"},
        ) as client:
            resp = await client.get(_FEED_URL)
            resp.raise_for_status()
        return _parse_atom_feed(resp.text)


def _parse_atom_feed(xml_text: str) -> list[Any]:
    """Parse Atom feed XML into SimpleNamespace objects mimicking feedparser entries."""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    entries = []
    for entry in root.findall("atom:entry", ns):
        def _text(tag: str) -> str:
            el = entry.find(tag, ns)
            return (el.text or "").strip() if el is not None else ""
        link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        entries.append(SimpleNamespace(
            title=_text("atom:title"),
            summary=_text("atom:summary"),
            link=link,
            updated=_text("atom:updated"),
        ))
    return entries
