"""mimic-signal: Real-time event detection for the Mimic ecosystem."""

from mimic_signal.monitor import SignalMonitor
from mimic_signal.signal import Signal, WeakSignal
from mimic_signal.weak_signals.detector import WeakSignalDetector
from mimic_signal.weak_signals.patterns import WeakSignalPattern

__version__ = "0.1.0"

__all__ = [
    "SignalMonitor",
    "Signal",
    "WeakSignal",
    "WeakSignalDetector",
    "WeakSignalPattern",
]
