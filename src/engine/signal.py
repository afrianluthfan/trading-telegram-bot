"""
Signal orchestrator — combines Kill Box + FVG into actionable trade signals.
"""

from __future__ import annotations

import logging
import time

from src.config import Settings
from src.engine.fvg import detect_fvg
from src.engine.kill_box import compute_kill_box
from src.engine.models import (
    BracketCoords,
    Candle,
    Direction,
    EngineState,
    KillBox,
    Signal,
)

log = logging.getLogger(__name__)

# Binance testnet leverage tiers: (min_leverage, max_notional_usdt)
# Sorted by min_leverage descending.  Adjust for mainnet / per-symbol tiers.
LEVERAGE_TIERS: list[tuple[int, float]] = [
    (101, 50_000),
    (51, 250_000),
    (21, 3_000_000),
    (11, 20_000_000),
    (6, 40_000_000),
    (5, 100_000_000),
    (4, 120_000_000),
    (2, 300_000_000),
    (1, 500_000_000),
]


def max_notional_for_leverage(leverage: int) -> float:
    """Return the maximum notional (USDT) allowed for a given leverage tier."""
    for min_lev, cap in LEVERAGE_TIERS:
        if leverage >= min_lev:
            return cap
    return LEVERAGE_TIERS[-1][1]


def compute_bracket(
    direction: Direction,
    entry: float,
    kill_box: KillBox,
    settings: Settings,
) -> BracketCoords:
    """Compute entry, SL, TP, and position size for a bracket order."""
    raw_notional = settings.margin_cap * settings.leverage
    cap = max_notional_for_leverage(settings.leverage)
    notional = min(raw_notional, cap)
    if notional < raw_notional:
        log.warning(
            f"Notional clamped from {raw_notional:.0f} to {notional:.0f} USDT "
            f"(leverage tier limit at {settings.leverage}x)"
        )

    if direction == Direction.LONG:
        sl = entry * (1 - settings.sl_delta)
        tp = kill_box.high_4h - (kill_box.macro_range * 0.382)
    else:
        sl = entry * (1 + settings.sl_delta)
        tp = kill_box.low_4h + (kill_box.macro_range * 0.382)

    contracts = notional / entry

    return BracketCoords(
        entry=entry,
        stop_loss=sl,
        take_profit=tp,
        contracts=contracts,
    )


def evaluate_signal(
    state: EngineState,
    candles_4h: list[Candle],
    candles_5m: list[Candle],
    settings: Settings,
) -> Signal | None:
    """
    Run the full signal evaluation pipeline.

    Called on every closed 5m candle. Returns a Signal if all conditions align,
    or None if no valid setup exists.
    """
    # Recompute Kill Box from 4H buffer
    kill_box = compute_kill_box(candles_4h)
    if kill_box is None:
        return None
    state.kill_box = kill_box

    # Cooldown check
    if state.cooldown_remaining > 0:
        state.cooldown_remaining -= 1
        log.debug(f"{state.symbol} cooldown: {state.cooldown_remaining} candles remaining")
        return None

    # Current price is the close of the latest 5m candle
    if not candles_5m:
        return None
    current_price = candles_5m[-1].close

    # Check which zone the price is in
    in_long = kill_box.price_in_long_zone(current_price)
    in_short = kill_box.price_in_short_zone(current_price)

    if not in_long and not in_short:
        return None

    # Detect FVG
    fvg = detect_fvg(candles_5m)
    if fvg is None:
        return None

    # FVG direction must match the Kill Box zone
    if fvg.direction == Direction.LONG and not in_long:
        return None
    if fvg.direction == Direction.SHORT and not in_short:
        return None

    # Compute bracket coordinates
    bracket = compute_bracket(fvg.direction, fvg.entry, kill_box, settings)

    signal = Signal(
        symbol=state.symbol,
        direction=fvg.direction,
        bracket=bracket,
        kill_box=kill_box,
        fvg=fvg,
        timestamp=int(time.time() * 1000),
    )

    log.info(
        f"SIGNAL: {signal.direction.name} {signal.symbol} | "
        f"Entry={bracket.entry:.2f} SL={bracket.stop_loss:.2f} TP={bracket.take_profit:.2f} "
        f"Qty={bracket.contracts:.4f}"
    )

    return signal
