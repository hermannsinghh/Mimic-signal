"""SignalMonitor — the main entry point for real-time event detection."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd

from mimic_signal.deduplicator import Deduplicator
from mimic_signal.relevance import RelevanceMatcher
from mimic_signal.scorer import SignalScorer
from mimic_signal.signal import Signal
from mimic_signal.sources.base import SignalSource
from mimic_signal.weak_signals.detector import WeakSignalDetector

logger = logging.getLogger(__name__)

# ─── source registry ──────────────────────────────────────────────────────────

def _build_registry() -> dict[str, type[SignalSource]]:
    from mimic_signal.sources.ais import AISSource
    from mimic_signal.sources.fred import FREDSource
    from mimic_signal.sources.gdelt import GDELTSource
    from mimic_signal.sources.newsapi import NewsAPISource
    from mimic_signal.sources.options import OptionsSource
    from mimic_signal.sources.sec_8k import SEC8KSource
    from mimic_signal.sources.twitter import TwitterSource
    return {
        "gdelt":        GDELTSource,
        "sec_8k":       SEC8KSource,
        "fred":         FREDSource,
        "newsapi":      NewsAPISource,
        "ais_vessels":  AISSource,
        "options":      OptionsSource,
        "twitter":      TwitterSource,
    }


def _make_source(name: str) -> SignalSource:
    registry = _build_registry()
    if name not in registry:
        raise ValueError(
            f"Unknown source: {name!r}. Available: {sorted(registry)}"
        )
    return registry[name]()


# ─── SignalMonitor ─────────────────────────────────────────────────────────────


class SignalMonitor:
    """Watches configured sources and fires callbacks when signals exceed threshold.

    Quick start::

        monitor = SignalMonitor(threshold=0.6)
        monitor.watch(["gdelt", "sec_8k", "fred"])

        @monitor.on_signal(threshold=0.65)
        def handle(signal: Signal, affected_twins: list):
            print(signal)

        monitor.start()  # blocking

    Non-blocking (Jupyter / integrations)::

        monitor.start_async()
        await asyncio.sleep(60)
        df = monitor.signal_log()
    """

    def __init__(
        self,
        twins: list[Any] | None = None,
        world: Any | None = None,
        threshold: float = 0.5,
    ) -> None:
        self.twins = twins or []
        self.world = world
        self.threshold = threshold

        self._sources: list[SignalSource] = []
        self._handlers: list[tuple[Callable, float]] = []
        self._signal_history: list[Signal] = []

        self._scorer = SignalScorer()
        self._deduplicator = Deduplicator()
        self._relevance = RelevanceMatcher(self.twins)
        self._weak = WeakSignalDetector()

        self._running = False
        self._task: asyncio.Task | None = None

    # ── configuration ────────────────────────────────────────────────────────

    def watch(self, sources: list[str]) -> None:
        """Configure which signal sources to poll."""
        self._sources = [_make_source(name) for name in sources]
        logger.info("Watching sources: %s", [s.name for s in self._sources])

    def on_signal(self, threshold: float | None = None) -> Callable:
        """Decorator to register a signal handler.

        The decorated function receives ``(signal: Signal, affected_twins: list)``.
        It may be a plain function or a coroutine.
        """
        effective = threshold if threshold is not None else self.threshold

        def decorator(fn: Callable) -> Callable:
            self._handlers.append((fn, effective))
            return fn

        return decorator

    def on_weak_signal(self, pattern_name: str) -> Callable:
        """Decorator to register a weak-signal handler for a named pattern."""
        self._weak.watch_for(pattern_name)
        return self._weak.on_weak_signal(pattern_name)

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Block and run the monitor until KeyboardInterrupt or stop()."""
        logger.info("SignalMonitor starting (blocking)")
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            logger.info("SignalMonitor stopped by user")

    def start_async(self) -> asyncio.Task:
        """Schedule the monitor on the running event loop (non-blocking)."""
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run())
        logger.info("SignalMonitor started (async)")
        return self._task

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("SignalMonitor stopped")

    # ── signal history ────────────────────────────────────────────────────────

    def recent_signals(self, hours: int = 24) -> list[Signal]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [s for s in self._signal_history if s.detected_at >= cutoff]

    def signal_log(self) -> pd.DataFrame:
        if not self._signal_history:
            return pd.DataFrame(columns=[
                "id", "title", "category", "severity", "confidence",
                "strength", "source", "detected_at", "event_date",
                "affected_sectors", "affected_geographies",
            ])
        return pd.DataFrame([
            {
                "id": s.id,
                "title": s.title,
                "category": s.category,
                "severity": s.severity,
                "confidence": s.confidence,
                "strength": s.strength,
                "source": s.source,
                "detected_at": s.detected_at,
                "event_date": s.event_date,
                "affected_sectors": ", ".join(s.affected_sectors),
                "affected_geographies": ", ".join(s.affected_geographies),
            }
            for s in self._signal_history
        ])

    # ── internal loop ─────────────────────────────────────────────────────────

    async def _run(self) -> None:
        self._running = True
        if not self._sources:
            logger.warning("No sources configured — call watch() first")
            return

        source_tasks = [
            asyncio.create_task(self._poll_loop(source), name=f"poll_{source.name}")
            for source in self._sources
        ]
        try:
            await asyncio.gather(*source_tasks)
        except asyncio.CancelledError:
            for task in source_tasks:
                task.cancel()
            await asyncio.gather(*source_tasks, return_exceptions=True)

    async def _poll_loop(self, source: SignalSource) -> None:
        while self._running:
            try:
                raw_signals = await source.poll()
                if raw_signals:
                    await self._process(raw_signals)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Error polling %s: %s", source.name, exc)
            await asyncio.sleep(source.poll_interval)

    async def _process(self, signals: list[Signal]) -> None:
        for signal in signals:
            scored = self._scorer.score(signal)

            if self._deduplicator.is_duplicate(scored):
                logger.debug("Deduped: %s", scored.title[:60])
                continue

            self._deduplicator.add(scored)
            self._signal_history.append(scored)
            affected = self._relevance.match(scored)

            strength = scored.strength
            logger.info(
                "SIGNAL [%s] %s | strength=%.2f | affected=%d twins",
                scored.source, scored.title[:70], strength, len(affected),
            )

            for handler, threshold in self._handlers:
                if strength >= threshold:
                    try:
                        result = handler(scored, affected)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as exc:
                        logger.error("Handler raised: %s", exc)
