"""
Kline stream subscription and candle buffer management.

Maintains rolling deques of closed candles for the signal engine.
Bootstraps initial history from REST on startup.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Callable, Coroutine

from src.engine.models import Candle
from src.execution.client import BinanceClient

log = logging.getLogger(__name__)


class KlineBuffers:
    """
    Manages candle buffers for one symbol across multiple intervals.

    Buffers are populated from REST on startup, then kept current
    via WebSocket kline messages.
    """

    def __init__(
        self,
        symbol: str,
        on_candle_close: Callable[[str, str, Candle], Coroutine] | None = None,
    ) -> None:
        self.symbol = symbol.upper()
        self._on_candle_close = on_candle_close

        # interval -> deque of closed Candle objects
        self._buffers: dict[str, deque[Candle]] = {}
        # interval -> currently forming (unclosed) candle
        self._live: dict[str, Candle | None] = {}

    def register_interval(self, interval: str, max_len: int) -> None:
        """Register an interval to track (e.g., '4h' with max_len=20)."""
        self._buffers[interval] = deque(maxlen=max_len)
        self._live[interval] = None

    async def bootstrap(self, client: BinanceClient, interval: str, limit: int) -> None:
        """
        Fetch historical klines via REST and populate the buffer.
        Called once at startup before WebSocket connects.
        """
        log.info(f"Bootstrapping {self.symbol} {interval} candles (limit={limit})")
        raw = await client.fetch_klines(self.symbol, interval, limit + 1)

        if not raw or not isinstance(raw, list):
            log.error(f"Bootstrap failed for {self.symbol} {interval}: {raw}")
            return

        buf = self._buffers[interval]
        for row in raw:
            candle = Candle.from_kline_rest(row)
            # Last row may be the currently open candle
            if row == raw[-1]:
                self._live[interval] = Candle(
                    timestamp=candle.timestamp,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    closed=False,
                )
            else:
                buf.append(candle)

        log.info(f"Bootstrapped {len(buf)} closed {interval} candles for {self.symbol}")

    async def handle_kline(self, data: dict[str, Any]) -> None:
        """
        Process a kline WebSocket message.

        Expected format (combined stream wrapper):
            {"stream": "btcusdt@kline_5m", "data": {"e": "kline", "k": {...}}}
        """
        k = data.get("k", {})
        if not k:
            return

        interval = k.get("i", "")
        if interval not in self._buffers:
            return

        candle = Candle.from_kline_ws(k)

        if candle.closed:
            buf = self._buffers[interval]
            buf.append(candle)
            self._live[interval] = None

            log.debug(
                f"{self.symbol} {interval} candle closed: "
                f"O={candle.open} H={candle.high} L={candle.low} C={candle.close}"
            )

            if self._on_candle_close:
                await self._on_candle_close(self.symbol, interval, candle)
        else:
            self._live[interval] = candle

    def get_closed(self, interval: str) -> list[Candle]:
        """Return list of closed candles for an interval (oldest first)."""
        return list(self._buffers.get(interval, []))

    def get_live(self, interval: str) -> Candle | None:
        """Return the currently forming (unclosed) candle."""
        return self._live.get(interval)

    @property
    def stream_names(self) -> list[str]:
        """Generate Binance stream names for all registered intervals."""
        sym = self.symbol.lower()
        return [f"{sym}@kline_{iv}" for iv in self._buffers]
