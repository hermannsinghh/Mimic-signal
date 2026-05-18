"""WeakSignalDetector — maintains data buffers and checks patterns on update."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

from mimic_signal.signal import WeakSignal
from mimic_signal.weak_signals.library import PATTERN_REGISTRY, ALL_PATTERNS
from mimic_signal.weak_signals.patterns import WeakSignalPattern

logger = logging.getLogger(__name__)

_DEFAULT_BUFFER = 100  # data points to retain per series


class WeakSignalDetector:
    """Watches time-series data for weak signal patterns.

    Usage::

        detector = WeakSignalDetector()
        detector.watch_for("bdi_decline_precedes_shipping_disruption")

        @detector.on_weak_signal("bdi_decline_precedes_shipping_disruption")
        def handle(ws: WeakSignal):
            print(ws)

        # Feed data in as it arrives
        detector.update("bdi_daily", 1800.0)
        detector.update("bdi_daily", 1710.0)  # ...
    """

    def __init__(self, buffer_size: int = _DEFAULT_BUFFER) -> None:
        self._buffer_size = buffer_size
        self._patterns: dict[str, WeakSignalPattern] = {}
        self._handlers: dict[str, list[Callable[[WeakSignal], Any]]] = defaultdict(list)
        self._buffers: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._buffer_size)
        )
        self._fired: dict[str, datetime] = {}  # pattern_name → last fire time
        self._cooldown_hours: float = 24.0

    def watch_for(self, pattern_name: str) -> None:
        """Register a pattern to watch by name (from the library or custom)."""
        if pattern_name not in PATTERN_REGISTRY:
            raise ValueError(
                f"Unknown pattern: {pattern_name!r}. "
                f"Available: {list(PATTERN_REGISTRY)}"
            )
        self._patterns[pattern_name] = PATTERN_REGISTRY[pattern_name]
        logger.debug("WeakSignalDetector: watching %s", pattern_name)

    def watch_all(self) -> None:
        """Register all 10 library patterns."""
        for pattern in ALL_PATTERNS:
            self._patterns[pattern.name] = pattern

    def add_pattern(self, pattern: WeakSignalPattern) -> None:
        """Register a custom pattern not in the library."""
        self._patterns[pattern.name] = pattern
        PATTERN_REGISTRY[pattern.name] = pattern

    def on_weak_signal(self, pattern_name: str) -> Callable:
        """Decorator to register a handler for a specific pattern."""
        def decorator(fn: Callable) -> Callable:
            self._handlers[pattern_name].append(fn)
            return fn
        return decorator

    def update(self, series_name: str, value: float) -> list[WeakSignal]:
        """Feed one new data point and return any newly triggered weak signals."""
        self._buffers[series_name].append(value)
        return self._check_patterns(series_name)

    def update_series(self, series_name: str, values: list[float]) -> list[WeakSignal]:
        """Bulk-update a series (e.g. backfill historical data)."""
        for v in values:
            self._buffers[series_name].append(v)
        return self._check_patterns(series_name)

    def get_series(self, series_name: str) -> pd.Series:
        return pd.Series(list(self._buffers[series_name]))

    def _check_patterns(self, updated_series: str) -> list[WeakSignal]:
        results: list[WeakSignal] = []
        for pattern_name, pattern in self._patterns.items():
            if updated_series not in pattern.features:
                continue
            series = self.get_series(updated_series)
            try:
                triggered, score = pattern.detect(series)
            except Exception as exc:
                logger.debug("Pattern %s detection error: %s", pattern_name, exc)
                continue

            if not triggered:
                continue
            if self._in_cooldown(pattern_name):
                continue

            ws = WeakSignal(
                pattern_name=pattern_name,
                precedes=pattern.precedes,
                title=f"[Weak Signal] {pattern.precedes.title()} — {pattern_name}",
                description=pattern.description,
                signal_value=score,
                confidence=pattern.historical_precision,
                lead_time_min_days=pattern.lead_time_days[0],
                lead_time_max_days=pattern.lead_time_days[1],
                detected_at=datetime.now(timezone.utc),
                source_series=updated_series,
                keywords=pattern.keywords,
            )
            self._fired[pattern_name] = ws.detected_at
            results.append(ws)

            for handler in self._handlers.get(pattern_name, []):
                try:
                    handler(ws)
                except Exception as exc:
                    logger.error("WeakSignal handler error: %s", exc)

        return results

    def _in_cooldown(self, pattern_name: str) -> bool:
        last = self._fired.get(pattern_name)
        if last is None:
            return False
        elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return elapsed < self._cooldown_hours
