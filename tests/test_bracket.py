"""Tests for bracket coordinate calculation."""

from src.engine.models import BracketCoords, Direction, KillBox
from src.engine.signal import compute_bracket, max_notional_for_leverage
from src.config import Settings


def _default_settings(**overrides) -> Settings:
    defaults = {
        "binance_api_key": "test",
        "binance_api_secret": "test",
        "margin_cap": 1000,
        "leverage": 150,
        "sl_delta": 0.0015,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _kill_box(high=70000, low=60000) -> KillBox:
    macro_range = high - low
    return KillBox(
        high_4h=high,
        low_4h=low,
        macro_range=macro_range,
        long_fib_0618=high - (macro_range * 0.618),
        long_fib_0786=high - (macro_range * 0.786),
        short_fib_0618=low + (macro_range * 0.618),
        short_fib_0786=low + (macro_range * 0.786),
    )


def test_long_bracket_coords():
    """
    Entry = 63000 (high[2] of FVG)
    SL = 63000 * 0.9985 = 62905.50
    TP = 70000 - (10000 * 0.382) = 66180
    Raw notional = 1000 * 150 = 150000, clamped to 50000 (tier limit at 101x+)
    Contracts = 50000 / 63000 ≈ 0.7937
    """
    settings = _default_settings()
    kb = _kill_box()
    bracket = compute_bracket(Direction.LONG, 63000, kb, settings)

    assert abs(bracket.entry - 63000) < 0.01
    assert abs(bracket.stop_loss - 62905.50) < 0.01
    assert abs(bracket.take_profit - 66180) < 0.01
    assert abs(bracket.contracts - 50000 / 63000) < 0.0001


def test_short_bracket_coords():
    """
    Entry = 67000 (low[2] of FVG)
    SL = 67000 * 1.0015 = 67100.50
    TP = 60000 + (10000 * 0.382) = 63820
    Raw notional = 1000 * 150 = 150000, clamped to 50000 (tier limit at 101x+)
    Contracts = 50000 / 67000 ≈ 0.7463
    """
    settings = _default_settings()
    kb = _kill_box()
    bracket = compute_bracket(Direction.SHORT, 67000, kb, settings)

    assert abs(bracket.entry - 67000) < 0.01
    assert abs(bracket.stop_loss - 67100.50) < 0.01
    assert abs(bracket.take_profit - 63820) < 0.01
    assert abs(bracket.contracts - 50000 / 67000) < 0.0001


def test_margin_cap_respected():
    """Notional = margin_cap * leverage. Contracts = notional / entry."""
    settings = _default_settings(margin_cap=500, leverage=100)
    kb = _kill_box()
    bracket = compute_bracket(Direction.LONG, 50000, kb, settings)

    expected_contracts = (500 * 100) / 50000  # 1.0
    assert abs(bracket.contracts - expected_contracts) < 0.0001


def test_custom_sl_delta():
    settings = _default_settings(sl_delta=0.002)
    kb = _kill_box()
    bracket = compute_bracket(Direction.LONG, 63000, kb, settings)

    expected_sl = 63000 * (1 - 0.002)  # 62874
    assert abs(bracket.stop_loss - expected_sl) < 0.01


# ── leverage tier clamping ───────────────────────────────────────────


def test_max_notional_lookup():
    """Verify tier boundaries return correct caps."""
    assert max_notional_for_leverage(125) == 50_000
    assert max_notional_for_leverage(101) == 50_000
    assert max_notional_for_leverage(100) == 250_000
    assert max_notional_for_leverage(51) == 250_000
    assert max_notional_for_leverage(50) == 3_000_000
    assert max_notional_for_leverage(21) == 3_000_000
    assert max_notional_for_leverage(20) == 20_000_000
    assert max_notional_for_leverage(10) == 40_000_000
    assert max_notional_for_leverage(5) == 100_000_000
    assert max_notional_for_leverage(4) == 120_000_000
    assert max_notional_for_leverage(3) == 300_000_000
    assert max_notional_for_leverage(1) == 500_000_000


def test_notional_clamped_at_high_leverage():
    """margin_cap=5000 at 100x → raw 500k, clamped to 250k."""
    settings = _default_settings(margin_cap=5000, leverage=100)
    kb = _kill_box()
    bracket = compute_bracket(Direction.LONG, 50000, kb, settings)

    expected_contracts = 250_000 / 50000  # 5.0
    assert abs(bracket.contracts - expected_contracts) < 0.0001


def test_no_clamp_when_under_tier_limit():
    """margin_cap=500 at 100x → raw 50k, tier allows 250k → no clamp."""
    settings = _default_settings(margin_cap=500, leverage=100)
    kb = _kill_box()
    bracket = compute_bracket(Direction.LONG, 50000, kb, settings)

    expected_contracts = (500 * 100) / 50000  # 1.0
    assert abs(bracket.contracts - expected_contracts) < 0.0001
