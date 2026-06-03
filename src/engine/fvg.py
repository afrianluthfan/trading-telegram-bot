"""
5-minute Fair Value Gap detector.

Identifies bullish and bearish FVGs from the most recent 3 closed candles.
"""

from __future__ import annotations

from src.engine.models import Candle, Direction, FVG


def detect_fvg(candles_5m: list[Candle]) -> FVG | None:
    """
    Detect a Fair Value Gap from the last 3 closed 5m candles.

    Candle layout: candles[-3] = candle[2], candles[-2] = candle[1], candles[-1] = candle[0]

    Bullish FVG: low[0] > high[2] AND close[1] > open[1]
        → Entry at high[2] (bottom of the gap)

    Bearish FVG: high[0] < low[2] AND close[1] < open[1]
        → Entry at low[2] (top of the gap)
    """
    if len(candles_5m) < 3:
        return None

    c2 = candles_5m[-3]  # oldest — "candle[2]" in PineScript notation
    c1 = candles_5m[-2]  # middle — the expansion candle
    c0 = candles_5m[-1]  # newest — "candle[0]"

    # Bullish FVG: violent upward expansion leaves a gap
    if c0.low > c2.high and c1.close > c1.open:
        return FVG(
            direction=Direction.LONG,
            entry=c2.high,
            candle_time=c0.timestamp,
        )

    # Bearish FVG: violent downward expansion leaves a gap
    if c0.high < c2.low and c1.close < c1.open:
        return FVG(
            direction=Direction.SHORT,
            entry=c2.low,
            candle_time=c0.timestamp,
        )

    return None
