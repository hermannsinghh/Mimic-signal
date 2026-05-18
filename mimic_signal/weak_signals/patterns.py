"""WeakSignalPattern — defines a pattern that historically precedes major events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd


@dataclass
class WeakSignalPattern:
    """A time-series pattern that historically precedes a major event."""

    name: str
    precedes: str
    description: str
    lead_time_days: tuple[int, int]
    features: list[str]
    threshold: float
    historical_precision: float
    detect: Callable[[pd.Series], tuple[bool, float]]
    """
    detect(series) → (triggered: bool, score: float)

    score is a normalised 0-1 measure of how strongly the pattern is
    presenting (used as the WeakSignal.signal_value).
    """
    keywords: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"WeakSignalPattern(name={self.name!r}, "
            f"precedes={self.precedes!r}, "
            f"lead_time={self.lead_time_days}, "
            f"precision={self.historical_precision:.0%})"
        )
