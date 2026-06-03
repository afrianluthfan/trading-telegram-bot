"""
Institutional trap filter — validates Smart Money divergence via REST.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.config import Settings
from src.engine.models import Direction
from src.execution.client import BinanceClient

log = logging.getLogger(__name__)


async def _fetch_data(client: BinanceClient, endpoint: str, symbol: str) -> Any:
    """Fetch a single institutional data endpoint."""
    return await client.get(endpoint, {
        "symbol": symbol.upper(),
        "period": "5m",
        "limit": 2,
    })


async def verify_institutional_trap(
    client: BinanceClient,
    symbol: str,
    direction: Direction,
    settings: Settings,
) -> bool:
    """
    Pull Top Trader Positions, Retail Accounts, and Open Interest simultaneously.
    Verify the institutional divergence before authorizing execution.

    Long trap:  retail L/S < threshold, top L/S > threshold, OI rising
    Short trap: retail L/S > threshold, top L/S < threshold, OI rising
    """
    log.info(f"Interrogating institutional ledger for {direction.name} {symbol}...")

    if client.is_rate_limited:
        log.warning("Skipping institutional check — API weight too high.")
        return False

    results = await asyncio.gather(
        _fetch_data(client, "/futures/data/topLongShortPositionRatio", symbol),
        _fetch_data(client, "/futures/data/globalLongShortAccountRatio", symbol),
        _fetch_data(client, "/futures/data/openInterestHist", symbol),
        return_exceptions=True,
    )

    top_positions, retail_accounts, open_interest = results

    # Validate all responses
    for i, name in enumerate(["topPositions", "retailAccounts", "openInterest"]):
        if isinstance(results[i], Exception):
            log.error(f"Failed to fetch {name}: {results[i]}")
            return False
        if not results[i] or not isinstance(results[i], list) or len(results[i]) < 2:
            log.warning(f"Incomplete data from {name}: {results[i]}")
            return False

    current_top_ratio = float(top_positions[-1]["longShortRatio"])
    current_retail_ratio = float(retail_accounts[-1]["longShortRatio"])
    previous_oi = float(open_interest[-2]["sumOpenInterest"])
    current_oi = float(open_interest[-1]["sumOpenInterest"])
    oi_is_rising = current_oi > previous_oi

    log.info(f"DATA — Retail L/S: {current_retail_ratio:.4f}")
    log.info(f"DATA — Top Trader L/S: {current_top_ratio:.4f}")
    log.info(f"DATA — OI: {'Rising' if oi_is_rising else 'Falling'} ({previous_oi:.0f} → {current_oi:.0f})")

    if direction == Direction.LONG:
        if (
            current_retail_ratio < settings.long_retail_ls_max
            and current_top_ratio > settings.long_top_ls_min
            and oi_is_rising
        ):
            log.info("SMART MONEY TRAP VERIFIED — LONG authorized.")
            return True
    elif direction == Direction.SHORT:
        if (
            current_retail_ratio > settings.short_retail_ls_min
            and current_top_ratio < settings.short_top_ls_max
            and oi_is_rising
        ):
            log.info("SMART MONEY TRAP VERIFIED — SHORT authorized.")
            return True

    log.info("Institutional divergence not detected. Strike aborted.")
    return False
