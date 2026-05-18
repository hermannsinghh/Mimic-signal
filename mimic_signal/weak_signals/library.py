"""10 pre-built weak signal patterns from the mimic-signal pattern library."""

from __future__ import annotations

import numpy as np
import pandas as pd

from mimic_signal.weak_signals.patterns import WeakSignalPattern


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _pct_change_over(series: pd.Series, window: int) -> float | None:
    """Return (last - window_ago) / abs(window_ago), or None if insufficient data."""
    if len(series) < window + 1:
        return None
    base = series.iloc[-(window + 1)]
    latest = series.iloc[-1]
    if base == 0:
        return None
    return float((latest - base) / abs(base))


def _rolling_z(series: pd.Series, window: int = 20) -> float | None:
    """Z-score of the latest value relative to a rolling window."""
    if len(series) < window + 1:
        return None
    subset = series.iloc[-(window + 1):-1]
    mu, sigma = float(subset.mean()), float(subset.std())
    if sigma == 0:
        return None
    return float((series.iloc[-1] - mu) / sigma)


def _score_from_ratio(ratio: float, signal_threshold: float, max_ratio: float = 3.0) -> float:
    """Normalise a ratio to a 0-1 score."""
    excess = ratio - signal_threshold
    range_ = max_ratio - signal_threshold
    return min(max(excess / range_, 0.0), 1.0) if range_ > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 1: Baltic Dry Index decline
# ─────────────────────────────────────────────────────────────────────────────

def _detect_bdi_decline(series: pd.Series) -> tuple[bool, float]:
    change = _pct_change_over(series, window=10)
    if change is None:
        return False, 0.0
    triggered = change <= -0.15
    score = _score_from_ratio(abs(change), 0.15, 0.50) if triggered else 0.0
    return triggered, round(score, 3)


bdi_decline_precedes_shipping_disruption = WeakSignalPattern(
    name="bdi_decline_precedes_shipping_disruption",
    precedes="shipping disruption",
    description=(
        "Baltic Dry Index drops >15% over 10 trading days. "
        "Historically precedes broad shipping disruptions by 2-4 weeks."
    ),
    lead_time_days=(14, 28),
    features=["bdi_daily"],
    threshold=-0.15,
    historical_precision=0.72,
    detect=_detect_bdi_decline,
    keywords=["bdi", "baltic dry index", "shipping", "freight"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 2: Options unusual put spike
# ─────────────────────────────────────────────────────────────────────────────

def _detect_put_spike(series: pd.Series) -> tuple[bool, float]:
    """Series: daily put/call ratio for a ticker."""
    z = _rolling_z(series, window=20)
    if z is None:
        return False, 0.0
    triggered = z >= 2.5
    score = _score_from_ratio(z, 2.5, 5.0) if triggered else 0.0
    return triggered, round(score, 3)


options_put_spike_precedes_company_event = WeakSignalPattern(
    name="options_put_spike_precedes_company_event",
    precedes="company material event",
    description=(
        "Unusual PUT volume (z-score ≥ 2.5 vs 20-day baseline). "
        "Historically precedes material negative company events by 1-3 weeks."
    ),
    lead_time_days=(7, 21),
    features=["options_put_call_ratio"],
    threshold=2.5,
    historical_precision=0.68,
    detect=_detect_put_spike,
    keywords=["options", "put", "unusual flow"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 3: GDELT regional tone decline
# ─────────────────────────────────────────────────────────────────────────────

def _detect_gdelt_tone_decline(series: pd.Series) -> tuple[bool, float]:
    """Series: 7-day rolling average GDELT AvgTone for a region."""
    change = _pct_change_over(series, window=7)
    if change is None:
        return False, 0.0
    triggered = change <= -0.20
    score = _score_from_ratio(abs(change), 0.20, 0.60) if triggered else 0.0
    return triggered, round(score, 3)


gdelt_tone_decline_precedes_geopolitical_crisis = WeakSignalPattern(
    name="gdelt_tone_decline_precedes_geopolitical_crisis",
    precedes="geopolitical crisis",
    description=(
        "Regional GDELT AvgTone drops >20% (more negative) over 7 days. "
        "Historically precedes geopolitical escalation by 1-2 weeks."
    ),
    lead_time_days=(7, 14),
    features=["gdelt_regional_tone"],
    threshold=-0.20,
    historical_precision=0.65,
    detect=_detect_gdelt_tone_decline,
    keywords=["gdelt", "tone", "geopolitical", "escalation"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 4: Vessel queue growth at major ports
# ─────────────────────────────────────────────────────────────────────────────

def _detect_vessel_queue_growth(series: pd.Series) -> tuple[bool, float]:
    """Series: daily vessel count waiting at a port."""
    change = _pct_change_over(series, window=5)
    if change is None:
        return False, 0.0
    triggered = change >= 0.50
    score = _score_from_ratio(change, 0.50, 2.0) if triggered else 0.0
    return triggered, round(score, 3)


vessel_queue_growth_precedes_port_disruption = WeakSignalPattern(
    name="vessel_queue_growth_precedes_port_disruption",
    precedes="port disruption",
    description=(
        "AIS vessel queue at a major port grows >50% over 5 days. "
        "Historically precedes port congestion signals by 3-7 days."
    ),
    lead_time_days=(3, 7),
    features=["ais_vessel_queue"],
    threshold=0.50,
    historical_precision=0.80,
    detect=_detect_vessel_queue_growth,
    keywords=["vessel queue", "port", "ais", "congestion"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 5: Fed language shift (hawk/dove)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_fed_language_shift(series: pd.Series) -> tuple[bool, float]:
    """Series: hawkishness score (positive = hawkish, negative = dovish)."""
    z = _rolling_z(series, window=12)
    if z is None:
        return False, 0.0
    triggered = abs(z) >= 1.8
    score = _score_from_ratio(abs(z), 1.8, 3.5) if triggered else 0.0
    return triggered, round(score, 3)


fed_language_shift_precedes_rate_decision = WeakSignalPattern(
    name="fed_language_shift_precedes_rate_decision",
    precedes="Federal Reserve rate decision",
    description=(
        "Fed speech hawk/dove language score deviates significantly from baseline. "
        "Historically precedes rate surprises by 2-4 weeks."
    ),
    lead_time_days=(14, 28),
    features=["fed_hawkishness_score"],
    threshold=1.8,
    historical_precision=0.70,
    detect=_detect_fed_language_shift,
    keywords=["fed", "fomc", "interest rate", "monetary policy"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 6: PMI divergence (manufacturing vs services)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_pmi_divergence(series: pd.Series) -> tuple[bool, float]:
    """Series: (manufacturing PMI - services PMI), monthly."""
    if len(series) < 3:
        return False, 0.0
    latest_spread = float(series.iloc[-1])
    prior_avg = float(series.iloc[-3:-1].mean())
    shift = latest_spread - prior_avg
    triggered = shift <= -5.0  # manufacturing weakening relative to services
    score = _score_from_ratio(abs(shift), 5.0, 15.0) if triggered else 0.0
    return triggered, round(score, 3)


pmi_divergence_precedes_supply_shock = WeakSignalPattern(
    name="pmi_divergence_precedes_supply_shock",
    precedes="supply shock",
    description=(
        "Manufacturing PMI drops ≥5 points relative to services PMI. "
        "Historically precedes supply chain disruptions by 4-8 weeks."
    ),
    lead_time_days=(28, 56),
    features=["pmi_manufacturing_services_spread"],
    threshold=-5.0,
    historical_precision=0.62,
    detect=_detect_pmi_divergence,
    keywords=["pmi", "manufacturing", "supply shock", "industrial"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 7: Credit spread widening
# ─────────────────────────────────────────────────────────────────────────────

def _detect_credit_spread_widening(series: pd.Series) -> tuple[bool, float]:
    """Series: IG or HY credit spread in basis points."""
    change = _pct_change_over(series, window=10)
    if change is None:
        return False, 0.0
    triggered = change >= 0.15
    score = _score_from_ratio(change, 0.15, 0.50) if triggered else 0.0
    return triggered, round(score, 3)


credit_spread_widening_precedes_financial_stress = WeakSignalPattern(
    name="credit_spread_widening_precedes_financial_stress",
    precedes="financial market stress",
    description=(
        "Investment-grade or high-yield credit spreads widen >15% in 10 days. "
        "Historically precedes broader financial stress by 2-6 weeks."
    ),
    lead_time_days=(14, 42),
    features=["credit_spread_bps"],
    threshold=0.15,
    historical_precision=0.73,
    detect=_detect_credit_spread_widening,
    keywords=["credit spread", "high yield", "financial stress", "bonds"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 8: Airline capacity cuts
# ─────────────────────────────────────────────────────────────────────────────

def _detect_airline_capacity_cut(series: pd.Series) -> tuple[bool, float]:
    """Series: weekly airline available seat-miles (ASM) or route count."""
    change = _pct_change_over(series, window=4)
    if change is None:
        return False, 0.0
    triggered = change <= -0.08
    score = _score_from_ratio(abs(change), 0.08, 0.30) if triggered else 0.0
    return triggered, round(score, 3)


airline_capacity_cut_precedes_demand_shock = WeakSignalPattern(
    name="airline_capacity_cut_precedes_demand_shock",
    precedes="demand shock",
    description=(
        "Airline available seat-miles drop >8% over 4 weeks. "
        "Airlines cut capacity ahead of demand collapses; lead time 2-4 weeks."
    ),
    lead_time_days=(14, 28),
    features=["airline_asm_weekly"],
    threshold=-0.08,
    historical_precision=0.67,
    detect=_detect_airline_capacity_cut,
    keywords=["airline", "capacity", "demand", "travel"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 9: Freight futures backwardation
# ─────────────────────────────────────────────────────────────────────────────

def _detect_freight_backwardation(series: pd.Series) -> tuple[bool, float]:
    """Series: (front-month freight futures - 3-month futures), normalised."""
    if len(series) < 5:
        return False, 0.0
    latest = float(series.iloc[-1])
    triggered = latest > 0.05  # spot trading above futures → backwardation
    score = _score_from_ratio(latest, 0.05, 0.25) if triggered else 0.0
    return triggered, round(score, 3)


freight_futures_backwardation_precedes_shortage = WeakSignalPattern(
    name="freight_futures_backwardation_precedes_shortage",
    precedes="acute freight shortage",
    description=(
        "Freight futures go into backwardation (spot premium over forward). "
        "Indicates immediate scarcity; shortage typically materialises in 1-3 weeks."
    ),
    lead_time_days=(7, 21),
    features=["freight_futures_spread"],
    threshold=0.05,
    historical_precision=0.77,
    detect=_detect_freight_backwardation,
    keywords=["freight futures", "backwardation", "shipping", "shortage"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pattern 10: Earnings whisper divergence
# ─────────────────────────────────────────────────────────────────────────────

def _detect_whisper_divergence(series: pd.Series) -> tuple[bool, float]:
    """Series: (whisper EPS - consensus EPS) / abs(consensus EPS)."""
    if len(series) < 2:
        return False, 0.0
    latest = float(series.iloc[-1])
    triggered = abs(latest) >= 0.10  # ±10% divergence from consensus
    score = _score_from_ratio(abs(latest), 0.10, 0.40) if triggered else 0.0
    return triggered, round(score, 3)


earnings_whisper_divergence_precedes_surprise = WeakSignalPattern(
    name="earnings_whisper_divergence_precedes_surprise",
    precedes="earnings surprise",
    description=(
        "Earnings whisper numbers diverge ≥10% from analyst consensus. "
        "Historically precedes large earnings beats or misses by 1-2 weeks."
    ),
    lead_time_days=(7, 14),
    features=["whisper_consensus_divergence"],
    threshold=0.10,
    historical_precision=0.69,
    detect=_detect_whisper_divergence,
    keywords=["earnings", "whisper", "consensus", "surprise"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

ALL_PATTERNS: list[WeakSignalPattern] = [
    bdi_decline_precedes_shipping_disruption,
    options_put_spike_precedes_company_event,
    gdelt_tone_decline_precedes_geopolitical_crisis,
    vessel_queue_growth_precedes_port_disruption,
    fed_language_shift_precedes_rate_decision,
    pmi_divergence_precedes_supply_shock,
    credit_spread_widening_precedes_financial_stress,
    airline_capacity_cut_precedes_demand_shock,
    freight_futures_backwardation_precedes_shortage,
    earnings_whisper_divergence_precedes_surprise,
]

PATTERN_REGISTRY: dict[str, WeakSignalPattern] = {p.name: p for p in ALL_PATTERNS}
