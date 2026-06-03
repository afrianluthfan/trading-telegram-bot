"""
Binance Futures REST client — signed requests with API weight tracking.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any

import aiohttp

from src.config import Settings

log = logging.getLogger(__name__)


class BinanceClient:
    """Async Binance Futures REST client with HMAC signing and rate-limit awareness."""

    def __init__(self, settings: Settings, session: aiohttp.ClientSession) -> None:
        self._settings = settings
        self._session = session
        self._base = settings.binance_api_base.rstrip("/")
        self._api_key = settings.binance_api_key
        self._api_secret = settings.binance_api_secret
        self._weight_pause = settings.api_weight_pause_threshold
        self.last_weight: int = 0
        self._symbol_info: dict[str, dict] = {}

    # ── signing ──────────────────────────────────────────────────────

    def _sign(self, query: str) -> str:
        return hmac.new(
            self._api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()

    # ── core request ─────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        params = dict(params) if params else {}
        url = f"{self._base}{endpoint}"

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            signature = self._sign(qs)
            signed_body = f"{qs}&signature={signature}"

        headers = {"X-MBX-APIKEY": self._api_key}

        if signed:
            if method.upper() == "POST":
                # Send as form body — avoids yarl re-encoding the query string
                async with self._session.post(url, data=signed_body, headers=headers) as resp:
                    return await self._handle_response(resp, endpoint)
            elif method.upper() == "DELETE":
                final_url = f"{url}?{signed_body}"
                async with self._session.delete(final_url, headers=headers) as resp:
                    return await self._handle_response(resp, endpoint)
            else:
                # GET: simple params only (no JSON), yarl won't mangle them
                final_url = f"{url}?{signed_body}"
                async with self._session.get(final_url, headers=headers) as resp:
                    return await self._handle_response(resp, endpoint)
        else:
            async with self._session.request(method, url, params=params, headers=headers) as resp:
                return await self._handle_response(resp, endpoint)

    async def _handle_response(self, resp: aiohttp.ClientResponse, endpoint: str) -> Any:
        weight = resp.headers.get("X-MBX-USED-WEIGHT-1M")
        if weight is not None:
            self.last_weight = int(weight)
            log.info(f"[API WEIGHT] {endpoint} | {self.last_weight}/2400")

        if self.last_weight >= self._weight_pause:
            log.warning(
                f"API weight {self.last_weight} exceeds threshold {self._weight_pause}. "
                "Pausing requests."
            )

        if resp.status == 429:
            log.error("RATE LIMITED (429) — Binance is throttling this IP.")
        elif resp.status == 418:
            log.critical("IP BANNED (418) — Binance has auto-banned this IP.")

        content_type = resp.content_type or ""
        if "json" not in content_type:
            body = await resp.text()
            raise ValueError(
                f"Non-JSON response from {endpoint}: "
                f"status={resp.status}, content_type='{content_type}', url={resp.url}"
            )

        data = await resp.json()

        if resp.status >= 400:
            log.error(f"HTTP {resp.status} on {endpoint}: {data}")

        return data

    # ── public convenience methods ───────────────────────────────────

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", endpoint, params)

    async def get_signed(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", endpoint, params, signed=True)

    async def post_signed(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", endpoint, params, signed=True)

    async def delete_signed(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("DELETE", endpoint, params, signed=True)

    # ── Binance-specific helpers ─────────────────────────────────────

    async def fetch_klines(
        self, symbol: str, interval: str, limit: int = 20
    ) -> list[list]:
        """Fetch historical klines via REST for buffer bootstrapping."""
        data = await self.get("/fapi/v1/klines", {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        })
        return data

    async def set_leverage(self, symbol: str, leverage: int) -> Any:
        """Force the leverage tier on the exchange."""
        log.info(f"Setting leverage for {symbol} to {leverage}x")
        return await self.post_signed("/fapi/v1/leverage", {
            "symbol": symbol.upper(),
            "leverage": leverage,
        })

    async def get_balance(self) -> Any:
        """Fetch futures account balance."""
        return await self.get_signed("/fapi/v2/balance")

    async def cancel_all_orders(self, symbol: str) -> Any:
        """Cancel all open orders for a symbol."""
        log.info(f"Cancelling all open orders for {symbol}")
        return await self.delete_signed("/fapi/v1/allOpenOrders", {
            "symbol": symbol.upper(),
        })

    async def close_position(self, symbol: str) -> Any:
        """Close any open position for a symbol by fetching it and sending a counter-order."""
        positions = await self.get_signed("/fapi/v2/positionRisk", {
            "symbol": symbol.upper(),
        })
        results = []
        if not isinstance(positions, list):
            return positions
        for pos in positions:
            amt = float(pos.get("positionAmt", 0))
            if amt == 0:
                continue
            side = "SELL" if amt > 0 else "BUY"
            pos_side = pos.get("positionSide", "BOTH")
            log.info(f"Closing {symbol} position: amt={amt}, side={side}, positionSide={pos_side}")
            result = await self.post_signed("/fapi/v1/order", {
                "symbol": symbol.upper(),
                "side": side,
                "positionSide": pos_side,
                "type": "MARKET",
                "quantity": str(abs(amt)),
            })
            results.append(result)
        return results

    async def load_symbol_info(self, *symbols: str) -> None:
        """Fetch and cache precision info for the given symbols."""
        data = await self.get("/fapi/v1/exchangeInfo")
        want = {s.upper() for s in symbols}
        for s in data.get("symbols", []):
            if s["symbol"] in want:
                self._symbol_info[s["symbol"]] = s
        for sym in want & set(self._symbol_info):
            info = self._symbol_info[sym]
            log.info(
                f"Symbol info: {sym} "
                f"pricePrecision={info['pricePrecision']} "
                f"quantityPrecision={info['quantityPrecision']}"
            )
        missing = want - set(self._symbol_info)
        if missing:
            log.warning(f"Symbol info not found for: {missing}")

    def get_precision(self, symbol: str) -> tuple[int, int]:
        """Return (price_precision, quantity_precision) for a symbol."""
        info = self._symbol_info.get(symbol.upper())
        if not info:
            raise ValueError(
                f"No symbol info cached for {symbol}. Call load_symbol_info first."
            )
        return info["pricePrecision"], info["quantityPrecision"]

    def get_tick_step(self, symbol: str) -> tuple[float, float]:
        """Return (tick_size, step_size) from exchange PRICE_FILTER / LOT_SIZE."""
        info = self._symbol_info.get(symbol.upper())
        if not info:
            raise ValueError(
                f"No symbol info cached for {symbol}. Call load_symbol_info first."
            )
        tick = step = 0.0
        for f in info.get("filters", []):
            if f["filterType"] == "PRICE_FILTER":
                tick = float(f["tickSize"])
            elif f["filterType"] == "LOT_SIZE":
                step = float(f["stepSize"])
        if not tick or not step:
            raise ValueError(f"Missing PRICE_FILTER or LOT_SIZE for {symbol}")
        return tick, step

    @property
    def is_rate_limited(self) -> bool:
        return self.last_weight >= self._weight_pause
