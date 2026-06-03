"""Tests for the 4H Kill Box calculator."""

from src.engine.kill_box import compute_kill_box
from src.engine.models import Candle


def _make_candle(high: float, low: float, close: float = 0, open_: float = 0) -> Candle:
    return Candle(
        timestamp=0, open=open_ or close, high=high, low=low,
        close=close or high, volume=0, closed=True,
    )


def test_kill_box_requires_20_candles():
    candles = [_make_candle(100, 90) for _ in range(19)]
    assert compute_kill_box(candles) is None


def test_kill_box_basic_math():
    """
    20 candles with high=70000, low=60000 → range=10000
    Long 0.618 = 70000 - 6180 = 63820
    Long 0.786 = 70000 - 7860 = 62140
    Short 0.618 = 60000 + 6180 = 66180
    Short 0.786 = 60000 + 7860 = 67860
    """
    candles = []
    for i in range(20):
        if i == 0:
            candles.append(_make_candle(high=70000, low=60000))
        else:
            candles.append(_make_candle(high=65000, low=63000))

    kb = compute_kill_box(candles)
    assert kb is not None
    assert kb.high_4h == 70000
    assert kb.low_4h == 60000
    assert kb.macro_range == 10000

    assert abs(kb.long_fib_0618 - 63820) < 0.01
    assert abs(kb.long_fib_0786 - 62140) < 0.01
    assert abs(kb.short_fib_0618 - 66180) < 0.01
    assert abs(kb.short_fib_0786 - 67860) < 0.01


def test_price_in_long_zone():
    candles = [_make_candle(high=70000, low=60000)] + [
        _make_candle(high=65000, low=63000) for _ in range(19)
    ]
    kb = compute_kill_box(candles)
    assert kb is not None

    # 63000 is between 62140 and 63820 → in long zone
    assert kb.price_in_long_zone(63000) is True
    # 66500 is between 66180 and 67860 → in short zone, NOT long
    assert kb.price_in_long_zone(66500) is False
    # 61000 is below the long zone floor
    assert kb.price_in_long_zone(61000) is False


def test_price_in_short_zone():
    candles = [_make_candle(high=70000, low=60000)] + [
        _make_candle(high=65000, low=63000) for _ in range(19)
    ]
    kb = compute_kill_box(candles)
    assert kb is not None

    # 67000 is between 66180 and 67860 → in short zone
    assert kb.price_in_short_zone(67000) is True
    # 63000 is in long zone, not short
    assert kb.price_in_short_zone(63000) is False


def test_zero_range_returns_none():
    candles = [_make_candle(high=65000, low=65000) for _ in range(20)]
    assert compute_kill_box(candles) is None
