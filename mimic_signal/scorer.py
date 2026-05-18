"""Signal scoring pipeline — normalises and enriches raw signals from adapters."""

from __future__ import annotations

import re

from mimic_signal.signal import Signal

# Sector keywords used for inferring affected sectors when adapters don't set them
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "technology": ["tech", "software", "hardware", "semiconductor", "chip", "ai", "cloud", "cyber"],
    "energy": ["oil", "gas", "petroleum", "coal", "renewable", "solar", "wind", "lng"],
    "supply_chain": ["port", "shipping", "container", "freight", "logistics", "warehouse", "transport"],
    "finance": ["bank", "credit", "interest rate", "financial", "debt", "bond", "currency", "forex"],
    "retail": ["retail", "consumer", "store", "shopping", "e-commerce"],
    "manufacturing": ["factory", "plant", "production", "manufacturing", "industrial"],
    "labor": ["strike", "union", "labor", "worker", "workforce", "layoff", "employment"],
    "macro": ["gdp", "inflation", "cpi", "ppi", "fed", "central bank", "recession", "growth"],
}


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", text.lower()))


class SignalScorer:
    """Normalises severity and confidence, and enriches sector/geo tagging."""

    def score(self, signal: Signal) -> Signal:
        signal.severity = _clamp(signal.severity)
        signal.confidence = _clamp(signal.confidence)

        if not signal.affected_sectors:
            signal.affected_sectors = self._infer_sectors(signal)

        if not signal.keywords:
            signal.keywords = list(_tokenize(f"{signal.title} {signal.description}"))[:20]

        return signal

    def _infer_sectors(self, signal: Signal) -> list[str]:
        combined = f"{signal.title} {signal.description} {' '.join(signal.keywords)}".lower()
        matched: list[str] = []
        for sector, keywords in _SECTOR_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                matched.append(sector)
        return matched or ["general"]
