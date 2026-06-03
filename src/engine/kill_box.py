"""
4H Fibonacci Kill Box calculator.

Computes dual long/short zones from a 20-bar 4H candle buffer.
"""

from __future__ import annotations

from src.engine.models import Candle, KillBox


def compute_kill_box(candles_4h: list[Candle]) -> KillBox | None:
    """
    Compute the Kill Box from the most recent closed 4H candles.

    Requires at least 20 candles. Uses the highest high and lowest low
    over the lookback window to define the Fibonacci retracement zones.
    """
    if len(candles_4h) < 20:
        return None

    window = candles_4h[-20:]
    high_4h = max(c.high for c in window)
    low_4h = min(c.low for c in window)
    macro_range = high_4h - low_4h

    if macro_range <= 0:
        return None

    return KillBox(
        high_4h=high_4h,
        low_4h=low_4h,
        macro_range=macro_range,
        # Long zone: retracing DOWN from the high
        long_fib_0618=high_4h - (macro_range * 0.618),
        long_fib_0786=high_4h - (macro_range * 0.786),
        # Short zone: retracing UP from the low
        short_fib_0618=low_4h + (macro_range * 0.618),
        short_fib_0786=low_4h + (macro_range * 0.786),
    )
