"""Deduplication — prevents the same underlying event from firing multiple times."""

from __future__ import annotations

import re
from collections import deque
from datetime import datetime, timedelta, timezone

from mimic_signal.signal import Signal

_WINDOW_HOURS = 24     # only deduplicate within a rolling 24-hour window
_SIM_THRESHOLD = 0.55  # Jaccard similarity above this → duplicate


def _tokenize(text: str) -> frozenset[str]:
    """Lowercase alpha tokens of length ≥ 3, ignoring stop words."""
    stop = {"the", "and", "for", "are", "was", "has", "its", "this", "that", "with"}
    return frozenset(
        t for t in re.findall(r"[a-z]{3,}", text.lower()) if t not in stop
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


class Deduplicator:
    """Maintains a rolling window of recent signals and filters near-duplicates."""

    def __init__(self, window_hours: int = _WINDOW_HOURS, threshold: float = _SIM_THRESHOLD) -> None:
        self._window = timedelta(hours=window_hours)
        self._threshold = threshold
        self._history: deque[tuple[datetime, frozenset[str], str]] = deque()
        # (detected_at, tokens, category)

    def is_duplicate(self, signal: Signal) -> bool:
        self._expire()
        tokens = _tokenize(f"{signal.title} {signal.description}")
        for _, hist_tokens, hist_category in self._history:
            if hist_category != signal.category:
                continue
            if _jaccard(tokens, hist_tokens) >= self._threshold:
                return True
        return False

    def add(self, signal: Signal) -> None:
        tokens = _tokenize(f"{signal.title} {signal.description}")
        self._history.append((signal.detected_at, tokens, signal.category))

    def _expire(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._window
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()
