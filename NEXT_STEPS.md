# NEXT_STEPS.md — mimic-signal

## Status as of 2026-05-18

### Install
PASS (`pip install -e ".[dev]"` succeeds cleanly on Python 3.10+)

### Tests
88 passing, 0 failing.

```
tests/test_deduplicator.py  — 7 tests  (new/same/different signal dedup, threshold behavior)
tests/test_fred.py          — 6 tests  (calendar mode, API surprise, error handling)
tests/test_gdelt.py         — 10 tests (row parsing, relevance, severity, polling, dedup)
tests/test_monitor.py       — 16 tests (construction, watch, handlers, async, twin matching)
tests/test_scorer.py        — 8 tests  (severity/confidence clamping, sector/keyword inference)
tests/test_sec_8k.py        — 13 tests (item extraction, severity mapping, parse, poll, dedup)
tests/test_signal.py        — 8 tests  (strength formula, defaults, IDs, WeakSignal lead time)
tests/test_weak_signals.py  — 20 tests (BDI decline, vessel queue, credit spread, whisper,
                                         pattern registry, detector cooldown, custom patterns)

88 passed in 0.19s
```

### CI Workflow
ADDED (`.github/workflows/ci.yml`)

---

## What This Repo Does (One Paragraph)

`mimic-signal` is the real-time event detection layer of the mimic ecosystem. It watches seven data sources simultaneously — GDELT (global events, free, 15 min latency), SEC EDGAR 8-K filings (material event disclosures, free), FRED economic releases (macro surprises, free), NewsAPI (news with optional FinBERT scoring), AIS vessel tracking (port congestion, paid), options flow (unusual activity, paid), and Twitter/X (fastest but noisiest, paid) — and fires structured `Signal` objects the moment a significant event is detected. A `Deduplicator` suppresses repeated signals within a configurable time window, a `SignalScorer` normalizes severity and confidence and enriches signals with sector/keyword tags, and a `RelevanceMatcher` maps each signal to the affected company twins. The `WeakSignalDetector` module watches for leading-indicator patterns (BDI decline, credit spread widening, options whisper divergence) that historically precede macro shocks by days or weeks.

---

## What Is Already Built

- `mimic_signal/__init__.py` — public API; re-exports `SignalMonitor`, `Signal`, `WeakSignal`
- `mimic_signal/signal.py` — `Signal` and `WeakSignal` dataclasses; `strength` property (geometric mean of severity × confidence); unique ID generation
- `mimic_signal/monitor.py` — `SignalMonitor`: `watch(sources)`, `on_signal(threshold)` decorator, `start()` async polling loop, `recent_signals()`, `signal_log()` DataFrame, `_process()` internal dispatch
- `mimic_signal/scorer.py` — `SignalScorer`: clamps severity/confidence to [0,1], infers affected sectors and keywords from title/description
- `mimic_signal/deduplicator.py` — `Deduplicator`: configurable similarity threshold and time window; suppresses duplicate events across polling cycles
- `mimic_signal/relevance.py` — `RelevanceMatcher`: maps signal sectors/keywords to matching twins in a world graph
- `mimic_signal/sources/base.py` — `SignalSource` ABC: `poll()`, `is_available()`, credential check pattern
- `mimic_signal/sources/gdelt.py` — GDELT 2.0 adapter: 15-min event feed, row parsing, relevance filtering, severity/confidence from goldstein scale and article count
- `mimic_signal/sources/sec_8k.py` — SEC EDGAR 8-K adapter: EDGAR Atom feed polling, item type extraction (1.01, 2.06, etc.), severity mapping, dedup by filing link
- `mimic_signal/sources/fred.py` — FRED release calendar adapter: calendar mode (no key required) and API mode (FRED_API_KEY for surprise magnitude)
- `mimic_signal/sources/ais.py` — AIS vessel tracking adapter (requires `AIS_API_KEY`): port queue anomalies, shipping lane disruptions
- `mimic_signal/sources/newsapi.py` — NewsAPI/MediaStack adapter (requires `NEWSAPI_KEY`): optional FinBERT scoring via `[nlp]` extra
- `mimic_signal/sources/options.py` — Options unusual activity adapter (requires `UNUSUAL_WHALES_KEY` or `CBOE_KEY`)
- `mimic_signal/sources/twitter.py` — Twitter/X adapter (requires `TWITTER_BEARER_TOKEN`)
- `mimic_signal/weak_signals/patterns.py` — `WeakSignalPattern` dataclass: name, description, required series, detection function, lead time range, historical examples
- `mimic_signal/weak_signals/library.py` — 10 pre-built patterns: BDI decline, vessel queue growth, credit spread widening, options whisper divergence, and 6 more
- `mimic_signal/weak_signals/detector.py` — `WeakSignalDetector`: data buffer management, pattern evaluation, cooldown between fires, `watch_all()`, `get_series()`

---

## Immediate Next Tasks

**Priority 1 — Live GDELT smoke test**
Run `monitor.watch(["gdelt"])` for 30 minutes. Log every raw event fetched and every signal that passes the threshold. Confirm at least 1 signal fires (GDELT is very active — this should fire within minutes). Fix any polling errors, timeout issues, or `httpx` parsing failures encountered in live mode.

**Priority 2 — SEC 8-K live test**
Run `monitor.watch(["sec_8k"])` for 1 hour. Log every 8-K detected. Manually verify Item type classification (1.01, 2.06, etc.) is correct by checking 3 detected filings on EDGAR.gov. Look especially for misclassification of Item 9.01 (financial exhibits) as high-severity.

**Priority 3 — Deduplication window test**
Create `tests/test_deduplicator_window.py`. Fire the same signal twice within 24 hours — confirm the second one is suppressed. Fire it again after 25 hours (mock `datetime.now`) — confirm it passes through. The 24-hour dedup window is the core reliability guarantee of the system.

**Priority 4 — Signal → world auto-trigger**
In `monitor.py`, add method `monitor.auto_simulate(world, mode="tier3")`. When a signal fires above threshold, automatically: (1) call `RelevanceMatcher` to find affected twins, (2) create `Scenario.from_signal(signal)` in `mimic-world`, (3) run `world.run(scenario, subset=affected_twins)`, (4) print `WorldResult.financial_impacts`. This is the full autonomous pipeline demo connecting all six repos.

**Priority 5 — PyPI publish**
Package name: `mimic-signal`. Core dependencies: `mimic-framework`, `mimic-world`. Optional extras: `mimic-signal[ais]`, `mimic-signal[options]`, `mimic-signal[nlp]`. Run `python -m build && twine upload dist/*`.

---

## How to Run (Developer Quick Reference)

```bash
cd ~/Desktop/mimic/Mimic-signal
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v          # run tests
pip install -e ".[dev]"   # reinstall after changes
```

---

## Known Issues

- AIS, Options, and Twitter sources require paid API keys and cannot be integration-tested in CI without secrets — these sources should be marked with `pytest.mark.skipif(not os.getenv("AIS_API_KEY"), ...)` in any live tests.
- `monitor.auto_simulate()` is not yet implemented — it is Priority 4 above.
- No live integration test exists yet; all 88 tests use mocked HTTP responses via `respx`.

---

## Dependencies on Other Mimic Repos

- `mimic-world` — optional; `monitor.auto_simulate()` (planned) will call `World.run(scenario)` and `Scenario.from_signal(signal)`.
- `mimic-framework` — optional; twin relevance matching in `relevance.py` can accept `mimic.Twin` objects, but the module duck-types these and has no hard import.
