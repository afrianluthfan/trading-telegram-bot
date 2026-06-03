"""
Telegram bot — polling, commands, and notification sender.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from src.config import Settings

log = logging.getLogger(__name__)


class TelegramBot:
    """Lightweight Telegram bot using raw HTTP — no SDK dependency."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id
        self._is_testnet = settings.is_testnet
        self._session: aiohttp.ClientSession | None = None
        self._base = f"https://api.telegram.org/bot{self._token}"
        self._running = False
        self._get_status_callback = None
        self._get_balance_callback = None
        self._shutdown_callback = None
        self._simulate_callback = None

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    async def open(self) -> None:
        """Create a dedicated HTTP session for Telegram API calls."""
        # Force IPv4 — many VPS have broken IPv6 to Telegram
        connector = aiohttp.TCPConnector(family=2)  # AF_INET
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)

    async def close(self) -> None:
        """Close the dedicated session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def set_callbacks(
        self,
        get_status=None,
        get_balance=None,
        shutdown=None,
        simulate=None,
    ) -> None:
        """Register callbacks for bot commands."""
        self._get_status_callback = get_status
        self._get_balance_callback = get_balance
        self._shutdown_callback = shutdown
        self._simulate_callback = simulate

    # ── sending ──────────────────────────────────────────────────────

    async def send(self, text: str, chat_id: int | None = None) -> None:
        """Send a message. Prepends [TESTNET] if running on testnet."""
        if not self.enabled:
            return

        target = chat_id or self._chat_id
        if not target:
            return

        prefix = "[TESTNET] " if self._is_testnet else ""
        payload = {
            "chat_id": target,
            "text": f"{prefix}{text}",
            "parse_mode": "HTML",
        }

        try:
            async with self._session.post(
                f"{self._base}/sendMessage", json=payload,
            ) as resp:
                if not resp.ok:
                    body = await resp.text()
                    log.error(f"Telegram send failed: {resp.status} {body}")
        except asyncio.TimeoutError:
            log.warning("Telegram send timed out (10s) — network issue?")
        except Exception:
            log.exception("Failed to send Telegram message")

    async def notify_signal(self, text: str) -> None:
        """Send a trade signal notification."""
        await self.send(f"🎯 {text}")

    async def notify_execution(self, text: str) -> None:
        """Send a trade execution result."""
        await self.send(f"✅ {text}")

    async def notify_abort(self, text: str) -> None:
        """Send a trade abort notification."""
        await self.send(f"🚫 {text}")

    async def notify_error(self, text: str) -> None:
        """Send an error notification."""
        await self.send(f"⚠️ {text}")

    # ── polling ──────────────────────────────────────────────────────

    async def start_polling(self) -> None:
        """Long-polling loop for incoming Telegram commands."""
        if not self.enabled:
            log.info("Telegram bot disabled (no token/chat_id).")
            return

        self._running = True
        offset = 0

        log.info("Telegram bot polling started.")
        await self.send("Engine started. Awaiting signals.")

        while self._running:
            try:
                async with self._session.get(
                    f"{self._base}/getUpdates",
                    params={"timeout": 30, "offset": offset},
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as resp:
                    data = await resp.json()

                if not data.get("ok"):
                    log.error(f"Telegram getUpdates error: {data}")
                    await asyncio.sleep(2)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message") or update.get("edited_message")
                    if not msg:
                        continue

                    text = (msg.get("text") or "").strip()
                    chat_id = msg["chat"]["id"]

                    await self._handle_command(text, chat_id)

            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Telegram polling error")
                await asyncio.sleep(2)

    async def stop(self) -> None:
        self._running = False

    async def _handle_command(self, text: str, chat_id: int) -> None:
        """Route incoming commands."""
        if text.startswith("/start"):
            await self.send("MBG Sniper Entry online. 🔫", chat_id)

        elif text.startswith("/status"):
            if self._get_status_callback:
                status_text = await self._get_status_callback()
                await self.send(status_text, chat_id)
            else:
                await self.send("Status not available.", chat_id)

        elif text.startswith("/balance"):
            if self._get_balance_callback:
                balance_text = await self._get_balance_callback()
                await self.send(balance_text, chat_id)
            else:
                await self.send("Balance not available.", chat_id)

        elif text.startswith("/kill"):
            await self.send("⛔ Emergency shutdown initiated.", chat_id)
            if self._shutdown_callback:
                await self._shutdown_callback()

        elif text.startswith("/simulate"):
            if self._simulate_callback:
                await self.send("🧪 Running simulation...", chat_id)
                result_text = await self._simulate_callback()
                await self.send(result_text, chat_id)
            else:
                await self.send("Simulation not available.", chat_id)
