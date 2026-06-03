"""
Data models used across the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Direction(Enum):
    LONG = "buy"
    SHORT = "sell"


@dataclass(slots=True)
class Candle:
    """A single OHLCV candle."""
    timestamp: int      # open time in ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool        # True when the candle is final

    @classmethod
    def from_kline_ws(cls, k: dict) -> Candle:
        """Parse from Binance WebSocket kline payload (the 'k' sub-object)."""
        return cls(
            timestamp=int(k["t"]),
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            closed=bool(k["x"]),
        )

    @classmethod
    def from_kline_rest(cls, row: list) -> Candle:
        """Parse from Binance REST /fapi/v1/klines response row."""
        return cls(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            closed=True,
        )


@dataclass(slots=True)
class KillBox:
    """4H Fibonacci Kill Box boundaries."""
    high_4h: float
    low_4h: float
    macro_range: float
    # Long zone (retracing down from high)
    long_fib_0618: float
    long_fib_0786: float
    # Short zone (retracing up from low)
    short_fib_0618: float
    short_fib_0786: float

    def price_in_long_zone(self, price: float) -> bool:
        return self.long_fib_0786 <= price <= self.long_fib_0618

    def price_in_short_zone(self, price: float) -> bool:
        return self.short_fib_0618 <= price <= self.short_fib_0786


@dataclass(slots=True)
class FVG:
    """A detected Fair Value Gap."""
    direction: Direction
    entry: float        # high[2] for long, low[2] for short
    candle_time: int    # timestamp of the triggering candle


@dataclass(slots=True)
class BracketCoords:
    """Entry, stop-loss, and take-profit coordinates."""
    entry: float
    stop_loss: float
    take_profit: float
    contracts: float


@dataclass(slots=True)
class Signal:
    """A fully qualified trade signal ready for execution."""
    symbol: str
    direction: Direction
    bracket: BracketCoords
    kill_box: KillBox
    fvg: FVG
    timestamp: int      # when the signal was generated


@dataclass
class EngineState:
    """Mutable per-symbol state tracked by the signal engine."""
    symbol: str
    kill_box: KillBox | None = None
    cooldown_remaining: int = 0
    last_signal: Signal | None = None
    in_position: bool = False
