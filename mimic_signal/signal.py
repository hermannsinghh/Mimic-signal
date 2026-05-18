from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class Signal:
    title: str
    description: str
    category: str
    severity: float
    confidence: float
    source: str
    source_url: str
    detected_at: datetime
    event_date: datetime
    id: str = field(default_factory=lambda: str(uuid4()))
    affected_sectors: list[str] = field(default_factory=list)
    affected_geographies: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    @property
    def strength(self) -> float:
        """Geometric mean of severity and confidence."""
        return (self.severity * self.confidence) ** 0.5

    def __repr__(self) -> str:
        return (
            f"Signal(title={self.title!r}, category={self.category!r}, "
            f"severity={self.severity:.2f}, confidence={self.confidence:.2f}, "
            f"strength={self.strength:.2f})"
        )


@dataclass
class WeakSignal:
    """An early-warning signal that precedes a major event by days or weeks."""

    pattern_name: str
    precedes: str
    title: str
    description: str
    signal_value: float
    confidence: float
    lead_time_min_days: int
    lead_time_max_days: int
    detected_at: datetime
    id: str = field(default_factory=lambda: str(uuid4()))
    source_series: str = ""
    keywords: list[str] = field(default_factory=list)

    @property
    def lead_time_estimate(self) -> int:
        return (self.lead_time_min_days + self.lead_time_max_days) // 2

    def __repr__(self) -> str:
        return (
            f"WeakSignal(pattern={self.pattern_name!r}, "
            f"precedes={self.precedes!r}, "
            f"lead_time={self.lead_time_min_days}-{self.lead_time_max_days}d, "
            f"confidence={self.confidence:.2f})"
        )
