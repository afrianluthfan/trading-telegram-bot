"""
WebSocket connection manager for Binance Futures streams.

Handles connection, auto-reconnect, ping/pong, and 24h rotation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine

import aiohttp

log = logging.getLogger(__name__)

# Binance disconnects after 24h — reconnect proactively at 23h 50m
MAX_CONNECTION_AGE = 23 * 3600 + 50 * 60


class WSClient:
    """Persistent WebSocket connection to Binance Futures combined streams."""

    def __init__(
        self,
        ws_base: str,
        streams: list[str],
        on_message: Callable[[dict[str, Any]], Coroutine],
        reconnect_delay: float = 2.0,
    ) -> None:
        self._ws_base = ws_base.rstrip("/")
        self._streams = streams
        self._on_message = on_message
        self._reconnect_delay = reconnect_delay
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False
        self._connected_at: float = 0

    @property
    def url(self) -> str:
        stream_path = "/".join(self._streams)
        return f"{self._ws_base}/stream?streams={stream_path}"

    async def start(self, session: aiohttp.ClientSession) -> None:
        """Start the WebSocket listener loop."""
        self._session = session
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except (aiohttp.WSServerHandshakeError, aiohttp.ClientError, OSError) as e:
                log.warning(f"WebSocket connection error: {e}")
            except asyncio.CancelledError:
                break

            if self._running:
                log.info(f"Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)

    async def stop(self) -> None:
        """Gracefully stop the WebSocket connection."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def _connect_and_listen(self) -> None:
        assert self._session is not None
        log.info(f"Connecting to {self.url}")

        async with self._session.ws_connect(
            self.url,
            heartbeat=20,  # aiohttp handles ping/pong at this interval
            max_msg_size=0,
        ) as ws:
            self._ws = ws
            self._connected_at = time.monotonic()
            log.info(f"WebSocket connected. Streams: {self._streams}")

            async for msg in ws:
                # Check 24h rotation
                if time.monotonic() - self._connected_at > MAX_CONNECTION_AGE:
                    log.info("Approaching 24h limit — rotating connection.")
                    await ws.close()
                    return

                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = msg.json()
                        await self._on_message(data)
                    except Exception:
                        log.exception("Error processing WebSocket message")

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    log.error(f"WebSocket error: {ws.exception()}")
                    return

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    log.info("WebSocket closed by server.")
                    return
