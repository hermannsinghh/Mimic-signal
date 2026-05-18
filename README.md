# mimic-signal

**Real-time event detection for the Mimic ecosystem.**

mimic-signal answers one question: *What is happening right now that matters to your companies?*

It watches 7 data sources continuously and fires structured `Signal` objects the moment something significant occurs — port congestion, SEC filings, macro surprises, geopolitical escalation. It also includes a **Weak Signal System** that detects precursor patterns days or weeks before events become obvious.

```python
from mimic_signal import SignalMonitor, Signal

monitor = SignalMonitor(threshold=0.6)
monitor.watch(["gdelt", "sec_8k", "fred"])

@monitor.on_signal(threshold=0.65)
def handle(signal: Signal, affected_twins: list):
    print(f"SIGNAL: {signal.title}")
    print(f"Severity: {signal.severity:.2f} | Confidence: {signal.confidence:.2f}")
    print(f"Strength: {signal.strength:.2f}")

monitor.start()
```

---

## Installation

```bash
pip install mimic-signal
```

With NLP support (FinBERT scoring for NewsAPI):
```bash
pip install "mimic-signal[nlp]"
```

---

## Signal Sources

| Source | Tier | Cost | Update | Signal Quality |
|--------|------|------|--------|----------------|
| GDELT | Free | $0 | 15 min | Medium — global, noisy |
| SEC EDGAR 8-K | Free | $0 | Continuous | High — self-reported material events |
| FRED releases | Free | $0 | Scheduled | High — authoritative macro data |
| NewsAPI | Low-cost | ~$50/mo | 1 hr | Medium-High — needs NLP filter |
| AIS Vessel Tracking | Paid | ~$200/mo | Real-time | **Very High** — 48-72h lead time |
| Options Flow | Paid | ~$200/mo | Real-time | **Very High** — money talks |
| Twitter/X | Paid | ~$100/mo | Real-time | Low — fastest detection, highest noise |

### Configuring credentials

```bash
export NEWSAPI_KEY="your_key"
export FRED_API_KEY="your_key"      # optional — enables surprise magnitude
export AIS_API_KEY="your_key"       # required for AIS source
export AIS_PROVIDER="aishub"        # or "marinetraffic"
export UNUSUAL_WHALES_KEY="key"     # required for options source
export TWITTER_BEARER_TOKEN="key"   # required for Twitter source
```

### Open-source vs commercial

The open-source version applies delays:
- GDELT, NewsAPI: 24-hour delay
- SEC 8-K: 1-hour delay
- AIS, Options: disabled (require paid subscriptions)

For real-time signals: `export MIMIC_SIGNAL_COMMERCIAL=1`

---

## The Signal Object

```python
@dataclass
class Signal:
    id: str                          # UUID
    title: str
    description: str
    category: str                    # supply_chain | macro | geopolitical | labor | company_event
    severity: float                  # 0-1, how impactful is this event
    confidence: float                # 0-1, how sure are we this is real
    affected_sectors: list[str]
    affected_geographies: list[str]
    source: str
    source_url: str
    detected_at: datetime
    event_date: datetime
    keywords: list[str]

    @property
    def strength(self) -> float:     # geometric mean of severity × confidence
```

---

## Weak Signal System

Detect precursor patterns before events become obvious.

```python
from mimic_signal import SignalMonitor
from mimic_signal.signal import WeakSignal

monitor = SignalMonitor()

@monitor.on_weak_signal("bdi_decline_precedes_shipping_disruption")
def handle_weak(signal: WeakSignal, lead_time_estimate: int):
    print(f"WEAK SIGNAL: {signal.title}")
    print(f"Lead time estimate: {signal.lead_time_estimate} days")
```

### 10 pre-built patterns

| Pattern | Lead Time | Precision |
|---------|-----------|-----------|
| BDI decline → shipping disruption | 2-4 weeks | 72% |
| Options put spike → company event | 1-3 weeks | 68% |
| GDELT tone decline → geopolitical crisis | 1-2 weeks | 65% |
| Vessel queue growth → port disruption | 3-7 days | 80% |
| Fed language shift → rate decision | 2-4 weeks | 70% |
| PMI divergence → supply shock | 4-8 weeks | 62% |
| Credit spread widening → financial stress | 2-6 weeks | 73% |
| Airline capacity cut → demand shock | 2-4 weeks | 67% |
| Freight futures backwardation → shortage | 1-3 weeks | 77% |
| Earnings whisper divergence → surprise | 1-2 weeks | 69% |

### Using the WeakSignalDetector directly

```python
from mimic_signal.weak_signals import WeakSignalDetector

detector = WeakSignalDetector()
detector.watch_for("bdi_decline_precedes_shipping_disruption")

@detector.on_weak_signal("bdi_decline_precedes_shipping_disruption")
def handle(ws):
    print(ws)

# Feed data as it arrives
detector.update("bdi_daily", 1850.0)
detector.update("bdi_daily", 1810.0)
# ...
```

---

## Full World Integration

```python
from mimic import Twin
from mimic_world import World
from mimic_signal import SignalMonitor

world = World()
world.add_twin(Twin.from_ticker("WMT"))
world.add_twin(Twin.from_ticker("AAPL"))
world.add_twin(Twin.from_ticker("FDX"))

monitor = SignalMonitor(world=world, threshold=0.6)
monitor.watch(["gdelt", "sec_8k", "fred", "newsapi", "ais_vessels"])

@monitor.on_signal(threshold=0.65)
def handle(signal, affected_twins):
    from mimic_world import Scenario
    scenario = Scenario.from_signal(signal)
    result = World.subset(world, affected_twins).run(scenario)
    print(result.financial_impacts)

monitor.start()
```

---

## Async / Non-blocking

```python
import asyncio
from mimic_signal import SignalMonitor

monitor = SignalMonitor(threshold=0.6)
monitor.watch(["gdelt", "sec_8k"])

@monitor.on_signal()
async def handle(signal, affected):
    # async handlers are supported
    await notify_slack(signal)

# Non-blocking — returns a Task
task = monitor.start_async()

# ... do other work ...

recent = monitor.recent_signals(hours=24)
df = monitor.signal_log()
```

---

## Repo Structure

```
mimic_signal/
├── monitor.py              SignalMonitor — main entry point
├── signal.py               Signal + WeakSignal dataclasses
├── scorer.py               Normalisation + sector inference
├── deduplicator.py         24h rolling dedup window (Jaccard similarity)
├── relevance.py            Twin relevance matching
├── sources/
│   ├── base.py             SignalSource ABC
│   ├── gdelt.py            GDELT 15-min event feed
│   ├── sec_8k.py           SEC EDGAR 8-K RSS
│   ├── fred.py             FRED release calendar
│   ├── newsapi.py          NewsAPI / MediaStack
│   ├── ais.py              AIS vessel tracking
│   ├── options.py          Unusual options flow
│   └── twitter.py          Twitter/X financial signals
└── weak_signals/
    ├── detector.py         WeakSignalDetector
    ├── patterns.py         WeakSignalPattern dataclass
    └── library.py          10 pre-built patterns
```

---

## Build Phases

- **v0.1** (current): GDELT + SEC 8-K — two free sources, signal firing
- **v0.2**: FRED + NewsAPI + deduplication
- **v0.3**: Weak signal patterns + historical backtest
- **v1.0**: AIS tracking + full mimic-world integration + docs

---

## License

Apache 2.0
