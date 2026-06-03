"""Tests for the 5m FVG detector."""

from src.engine.fvg import detect_fvg
from src.engine.models import Candle, Direction


def _c(open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(timestamp=0, open=open_, high=high, low=low, close=close, volume=0, closed=True)


def test_no_fvg_with_insufficient_candles():
    assert detect_fvg([]) is None
    assert detect_fvg([_c(100, 101, 99, 100)]) is None
    assert detect_fvg([_c(100, 101, 99, 100), _c(100, 101, 99, 100)]) is None


def test_bullish_fvg_detected():
    """
    Bullish FVG: low[0] > high[2] AND close[1] > open[1]
    candle[2] (oldest): high=100
    candle[1] (middle, green expansion): open=99, close=105
    candle[0] (newest): low=101
    Gap: low[0]=101 > high[2]=100 ✓
    """
    c2 = _c(open_=98, high=100, low=97, close=99)    # oldest
    c1 = _c(open_=99, high=106, low=99, close=105)    # expansion (green)
    c0 = _c(open_=105, high=108, low=101, close=107)   # newest

    fvg = detect_fvg([c2, c1, c0])
    assert fvg is not None
    assert fvg.direction == Direction.LONG
    assert fvg.entry == 100  # high[2]


def test_bearish_fvg_detected():
    """
    Bearish FVG: high[0] < low[2] AND close[1] < open[1]
    candle[2] (oldest): low=100
    candle[1] (middle, red expansion): open=101, close=95
    candle[0] (newest): high=99
    Gap: high[0]=99 < low[2]=100 ✓
    """
    c2 = _c(open_=102, high=103, low=100, close=101)
    c1 = _c(open_=101, high=101, low=94, close=95)
    c0 = _c(open_=95, high=99, low=93, close=94)

    fvg = detect_fvg([c2, c1, c0])
    assert fvg is not None
    assert fvg.direction == Direction.SHORT
    assert fvg.entry == 100  # low[2]


def test_no_fvg_when_no_gap():
    """Candles overlap — no gap exists."""
    c2 = _c(open_=100, high=102, low=99, close=101)
    c1 = _c(open_=101, high=103, low=100, close=102)
    c0 = _c(open_=102, high=103, low=101, close=102)

    assert detect_fvg([c2, c1, c0]) is None


def test_no_bullish_fvg_when_middle_is_red():
    """Gap exists but middle candle is bearish — not a valid bullish FVG."""
    c2 = _c(open_=98, high=100, low=97, close=99)
    c1 = _c(open_=105, high=106, low=99, close=99)  # red candle
    c0 = _c(open_=105, high=108, low=101, close=107)

    assert detect_fvg([c2, c1, c0]) is None


def test_no_bearish_fvg_when_middle_is_green():
    """Gap exists downward but middle candle is bullish — not valid bearish FVG."""
    c2 = _c(open_=102, high=103, low=100, close=101)
    c1 = _c(open_=95, high=101, low=94, close=101)  # green candle
    c0 = _c(open_=95, high=99, low=93, close=94)

    assert detect_fvg([c2, c1, c0]) is None


def test_uses_last_three_candles_from_longer_list():
    """If more than 3 candles, only the last 3 matter."""
    noise = [_c(50, 55, 45, 52) for _ in range(10)]
    c2 = _c(open_=98, high=100, low=97, close=99)
    c1 = _c(open_=99, high=106, low=99, close=105)
    c0 = _c(open_=105, high=108, low=101, close=107)

    fvg = detect_fvg(noise + [c2, c1, c0])
    assert fvg is not None
    assert fvg.direction == Direction.LONG
