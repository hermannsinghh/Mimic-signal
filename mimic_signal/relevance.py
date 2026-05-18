"""Twin relevance matching — determines which companies in a world are affected."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from mimic_signal.signal import Signal


@runtime_checkable
class TwinLike(Protocol):
    """Minimal interface expected from a mimic Twin object."""

    @property
    def ticker(self) -> str: ...

    @property
    def sector(self) -> str: ...

    @property
    def geographies(self) -> list[str]: ...


# Fallback: if we can't use the Protocol, treat any object as a dict-like twin
def _get(obj: Any, key: str, default: str = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# S&P 500 sector → our signal sector mapping
_SECTOR_MAP: dict[str, list[str]] = {
    "technology":             ["technology", "supply_chain"],
    "information technology": ["technology"],
    "consumer discretionary": ["retail", "supply_chain", "labor"],
    "consumer staples":       ["retail", "supply_chain", "macro"],
    "industrials":            ["supply_chain", "manufacturing", "labor"],
    "materials":              ["supply_chain", "manufacturing"],
    "energy":                 ["energy", "geopolitical"],
    "financials":             ["finance", "macro"],
    "health care":            ["supply_chain", "macro"],
    "utilities":              ["energy", "macro"],
    "real estate":            ["macro", "finance"],
    "communication services": ["technology", "geopolitical"],
}


def _sector_overlap(twin_sector: str, signal_sectors: list[str]) -> bool:
    compatible = _SECTOR_MAP.get(twin_sector.lower(), [twin_sector.lower()])
    return any(s in compatible for s in signal_sectors)


def _geo_overlap(twin_geos: list[str], signal_geos: list[str]) -> bool:
    if not signal_geos or signal_geos == ["GLOBAL"]:
        return True
    twin_set = {g.upper() for g in twin_geos}
    sig_set = {g.upper() for g in signal_geos}
    return bool(twin_set & sig_set)


class RelevanceMatcher:
    """Matches a Signal to twins that are exposed to the event."""

    def __init__(self, twins: list[Any]) -> None:
        self._twins = twins

    def match(self, signal: Signal) -> list[Any]:
        """Return all twins affected by signal."""
        return [t for t in self._twins if self._is_affected(t, signal)]

    def _is_affected(self, twin: Any, signal: Signal) -> bool:
        sector = _get(twin, "sector", "general")
        geos: list[str] = _get(twin, "geographies", []) or []

        sector_hit = _sector_overlap(str(sector), signal.affected_sectors)
        geo_hit = _geo_overlap(list(geos), signal.affected_geographies)

        # Category-based special rules
        if signal.category == "company_event":
            # Keyword match against ticker
            ticker = str(_get(twin, "ticker", "")).lower()
            if ticker and ticker in " ".join(signal.keywords).lower():
                return True

        return sector_hit and (geo_hit or not signal.affected_geographies)
