"""
Bracket order construction and submission via /fapi/v1/order.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from src.engine.models import BracketCoords, Direction
from src.execution.client import BinanceClient

log = logging.getLogger(__name__)


def _truncate(value: float, decimals: int) -> float:
    """Truncate (floor) a float to the given number of decimal places."""
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def _round_to_tick(value: float, tick: float) -> float:
    """Round *down* to the nearest tick/step multiple."""
    return math.floor(value / tick) * tick


async def execute_bracket_order(
    client: BinanceClient,
    symbol: str,
    direction: Direction,
    bracket: BracketCoords,
) -> Any:
    """
    Submit entry + SL + TP as three individual orders.

    Uses GTX (Post-Only) for the entry to guarantee maker fees.
    Uses the Algo Order API for SL/TP (conditional orders).
    Includes positionSide for Hedge Mode compatibility.
    """
    tick, step = client.get_tick_step(symbol)
    price_prec, _ = client.get_precision(symbol)

    entry_price = round(_round_to_tick(bracket.entry, tick), price_prec)
    sl_price = round(_round_to_tick(bracket.stop_loss, tick), price_prec)
    tp_price = round(_round_to_tick(bracket.take_profit, tick), price_prec)
    qty = _round_to_tick(bracket.contracts, step)

    entry_side = direction.value.upper()     # BUY or SELL
    exit_side = "SELL" if entry_side == "BUY" else "BUY"
    position_side = "LONG" if direction == Direction.LONG else "SHORT"

    log.info(
        f"Submitting bracket order: {entry_side} {symbol} "
        f"entry={entry_price} sl={sl_price} tp={tp_price} qty={qty}"
    )

    results = []

    # 1. Maker entry
    entry_result = await client.post_signed("/fapi/v1/order", {
        "symbol": symbol.upper(),
        "side": entry_side,
        "positionSide": position_side,
        "type": "LIMIT",
        "timeInForce": "GTX",
        "quantity": str(qty),
        "price": str(entry_price),
    })
    results.append(entry_result)
    log.info(f"Entry order response: {entry_result}")

    # 2. Stop loss (algo conditional order)
    sl_result = await client.post_signed("/fapi/v1/algoOrder", {
        "symbol": symbol.upper(),
        "side": exit_side,
        "positionSide": position_side,
        "algoType": "CONDITIONAL",
        "type": "STOP_MARKET",
        "triggerPrice": str(sl_price),
        "quantity": str(qty),
    })
    results.append(sl_result)
    log.info(f"Stop loss order response: {sl_result}")

    # 3. Take profit (algo conditional order)
    tp_result = await client.post_signed("/fapi/v1/algoOrder", {
        "symbol": symbol.upper(),
        "side": exit_side,
        "positionSide": position_side,
        "algoType": "CONDITIONAL",
        "type": "TAKE_PROFIT_MARKET",
        "triggerPrice": str(tp_price),
        "quantity": str(qty),
    })
    results.append(tp_result)
    log.info(f"Take profit order response: {tp_result}")

    return results
