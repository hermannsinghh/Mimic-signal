from __future__ import annotations

import os
from abc import ABC, abstractmethod

from mimic_signal.signal import Signal


class SignalSource(ABC):
    """Abstract base for all signal data sources."""

    name: str = ""
    poll_interval: int = 900  # seconds between polls
    # Open-source delay; set MIMIC_SIGNAL_COMMERCIAL=1 to disable
    delay_hours: float = 24.0

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if os.getenv("MIMIC_SIGNAL_COMMERCIAL"):
            cls.delay_hours = 0.0

    @abstractmethod
    async def poll(self) -> list[Signal]:
        """Fetch new signals since the last poll."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if source is configured and credentials are present."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(delay={self.delay_hours}h)"
