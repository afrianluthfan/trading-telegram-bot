"""
MBG Sniper Entry — Main entry point.

Boots all subsystems: WebSocket, signal engine, institutional filter,
execution engine, and Telegram bot.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

import aiohttp

from src.config import Settings, load_settings
from src.engine.models import Candle, Direction, EngineState, FVG, Signal
from src.engine.signal import compute_bracket, evaluate_signal
from src.execution.bracket import execute_bracket_order
from src.execution.client import BinanceClient
from src.filter.institutional import verify_institutional_trap
from src.telegram.bot import TelegramBot
from src.ws.client import WSClient
from src.ws.streams import KlineBuffers

log = logging.getLogger(__name__)

# ── globals ──────────────────────────────────────────────────────────

settings: Settings
client: BinanceClient
telegram: TelegramBot
buffers: dict[str, KlineBuffers] = {}
states: dict[str, EngineState] = {}
shutdown_event: asyncio.Event


# ── candle close handler ─────────────────────────────────────────────

async def on_candle_close(symbol: str, interval: str, candle: Candle) -> None:
    """Called every time a kline candle closes."""
    if interval != "5m":
        # 4H candle close — just log it, Kill Box will recompute on next 5m eval
        if interval == "4h":
            log.info(f"{symbol} 4H candle closed: H={candle.high} L={candle.low}")
        return

    # 5m candle closed — run the signal engine
    buf = buffers.get(symbol)
    state = states.get(symbol)
    if not buf or not state:
        return

    candles_4h = buf.get_closed("4h")
    candles_5m = buf.get_closed("5m")

    sig = evaluate_signal(state, candles_4h, candles_5m, settings)
    if sig is None:
        return

    # Signal detected — notify
    signal_text = (
        f"<b>{sig.direction.name} {sig.symbol}</b>\n"
        f"Entry: {sig.bracket.entry:.2f}\n"
        f"SL: {sig.bracket.stop_loss:.2f}\n"
        f"TP: {sig.bracket.take_profit:.2f}\n"
        f"Qty: {sig.bracket.contracts:.4f}"
    )
    await telegram.notify_signal(signal_text)

    # Institutional filter
    trap_ok = await verify_institutional_trap(client, sig.symbol, sig.direction, settings)
    if not trap_ok:
        await telegram.notify_abort(
            f"{sig.direction.name} {sig.symbol} — Institutional divergence failed."
        )
        return

    # Execute
    try:
        await client.set_leverage(sig.symbol, settings.leverage)
        result = await execute_bracket_order(client, sig.symbol, sig.direction, sig.bracket)
        state.cooldown_remaining = settings.post_trade_cooldown
        state.last_signal = sig
        state.in_position = True

        await telegram.notify_execution(
            f"{sig.direction.name} {sig.symbol} bracket placed.\n"
            f"Entry: {sig.bracket.entry:.2f} | SL: {sig.bracket.stop_loss:.2f} | "
            f"TP: {sig.bracket.take_profit:.2f}\n"
            f"Exchange response: {result}"
        )
    except Exception as e:
        log.exception("Bracket order failed")
        await telegram.notify_error(f"Order failed: {e}")


# ── WebSocket message router ────────────────────────────────────────

async def on_ws_message(msg: dict[str, Any]) -> None:
    """Route combined stream messages to the correct buffer."""
    stream = msg.get("stream", "")
    data = msg.get("data", {})

    if "@kline_" not in stream:
        return

    # Extract symbol from stream name (e.g., "btcusdt@kline_5m" → "BTCUSDT")
    sym = stream.split("@")[0].upper()
    buf = buffers.get(sym)
    if buf:
        await buf.handle_kline(data)


# ── status / balance callbacks ───────────────────────────────────────

async def get_status() -> str:
    lines = []
    for sym, state in states.items():
        kb = state.kill_box
        buf = buffers.get(sym)
        live_5m = buf.get_live("5m") if buf else None
        price = live_5m.close if live_5m else "N/A"

        lines.append(f"<b>{sym}</b>")
        lines.append(f"  Price: {price}")
        if kb:
            lines.append(f"  4H High: {kb.high_4h:.2f} | Low: {kb.low_4h:.2f}")
            lines.append(f"  Long Zone: {kb.long_fib_0786:.2f}–{kb.long_fib_0618:.2f}")
            lines.append(f"  Short Zone: {kb.short_fib_0618:.2f}–{kb.short_fib_0786:.2f}")
            if isinstance(price, float):
                in_long = kb.price_in_long_zone(price)
                in_short = kb.price_in_short_zone(price)
                zone = "LONG KILL BOX" if in_long else "SHORT KILL BOX" if in_short else "None"
                lines.append(f"  Active Zone: {zone}")
        lines.append(f"  Cooldown: {state.cooldown_remaining}")
        lines.append(f"  In Position: {state.in_position}")

    lines.append(f"\nAPI Weight: {client.last_weight}/2400")
    return "\n".join(lines) if lines else "No symbols configured."


async def get_balance() -> str:
    try:
        balances = await client.get_balance()
        if isinstance(balances, list):
            usdt = next((b for b in balances if b.get("asset") == "USDT"), None)
            if usdt:
                return (
                    f"USDT Balance: {usdt.get('balance', 'N/A')}\n"
                    f"Available: {usdt.get('availableBalance', 'N/A')}"
                )
        return f"Raw response: {balances}"
    except Exception as e:
        return f"Balance fetch failed: {e}"


async def do_shutdown() -> None:
    shutdown_event.set()


# ── simulation ───────────────────────────────────────────────────────

async def simulate_signal() -> str:
    """
    Build a synthetic LONG signal from the live Kill Box and current price,
    then run it through the full pipeline: institutional filter → bracket → execute.

    This lets you verify the entire chain fires end-to-end on testnet.
    """
    sym = settings.symbol_list[0]
    state = states.get(sym)
    buf = buffers.get(sym)
    if not state or not buf:
        return "No symbol state available."

    candles_4h = buf.get_closed("4h")
    if len(candles_4h) < 20:
        return f"Not enough 4H candles ({len(candles_4h)}/20)."

    from src.engine.kill_box import compute_kill_box
    kb = compute_kill_box(candles_4h)
    if not kb:
        return "Cannot compute Kill Box."

    # Use the current live price as a fake FVG entry, offset slightly so the
    # GTX (Post-Only) limit order sits on the book instead of crossing the spread.
    live = buf.get_live("5m")
    price = live.close if live else candles_4h[-1].close
    price *= 0.998  # 0.2% below market → guaranteed maker for a LONG

    # Build a synthetic LONG signal
    from src.engine.signal import compute_bracket
    bracket = compute_bracket(Direction.LONG, price, kb, settings)

    sig = Signal(
        symbol=sym,
        direction=Direction.LONG,
        bracket=bracket,
        kill_box=kb,
        fvg=FVG(direction=Direction.LONG, entry=price, candle_time=0),
        timestamp=int(__import__("time").time() * 1000),
    )

    lines = [
        f"<b>🧪 SIMULATION — {sig.direction.name} {sym}</b>",
        f"Entry: {bracket.entry:.2f}",
        f"SL: {bracket.stop_loss:.2f}",
        f"TP: {bracket.take_profit:.2f}",
        f"Qty: {bracket.contracts:.4f}",
        "",
    ]

    # Step 1: Institutional filter
    lines.append("⏳ Checking institutional filter...")
    await telegram.send("\n".join(lines))

    trap_ok = await verify_institutional_trap(client, sym, Direction.LONG, settings)
    if not trap_ok:
        lines.append("🚫 Institutional filter FAILED (expected on most market conditions).")
        lines.append("")
        lines.append("⏳ Skipping filter — executing bracket order anyway (simulation)...")
    else:
        lines.append("✅ Institutional filter PASSED.")

    # Step 2: Set leverage
    try:
        lev_result = await client.set_leverage(sym, settings.leverage)
        lines.append(f"✅ Leverage set: {lev_result}")
    except Exception as e:
        lines.append(f"⚠️ Leverage failed: {e}")

    # Step 3: Cancel existing open orders and close positions to free notional
    try:
        cancel_result = await client.cancel_all_orders(sym)
        lines.append(f"✅ Cancelled open orders: {cancel_result}")
    except Exception as e:
        lines.append(f"⚠️ Cancel orders failed: {e}")

    try:
        close_result = await client.close_position(sym)
        if close_result:
            lines.append(f"✅ Closed existing position: {close_result}")
    except Exception as e:
        lines.append(f"⚠️ Close position failed: {e}")

    # Step 4: Submit bracket order
    try:
        result = await execute_bracket_order(client, sym, sig.direction, sig.bracket)
        lines.append(f"✅ Bracket order submitted.")

        # Parse response
        if isinstance(result, list):
            for i, order in enumerate(result):
                # Regular orders use orderId/status; algo orders use algoId/algoStatus
                order_id = order.get("orderId") or order.get("algoId", "N/A")
                status = order.get("status") or order.get("algoStatus") or order.get("msg", "unknown")
                lines.append(f"  Order {i+1}: id={order_id} status={status}")
        else:
            lines.append(f"  Response: {result}")

    except Exception as e:
        lines.append(f"❌ Bracket order failed: {e}")

    return "\n".join(lines)


# ── boot sequence ────────────────────────────────────────────────────

async def run() -> None:
    global settings, client, telegram, shutdown_event

    # Load config
    env_file = sys.argv[1] if len(sys.argv) > 1 else ".env"
    settings = load_settings(env_file)

    env_label = "TESTNET" if settings.is_testnet else "LIVE"
    log.info(f"Booting MBG Sniper Entry [{env_label}]")
    log.info(f"Symbols: {settings.symbol_list}")
    log.info(f"Leverage: {settings.leverage}x | Margin cap: {settings.margin_cap} USDT")

    shutdown_event = asyncio.Event()

    connector = aiohttp.TCPConnector(keepalive_timeout=60)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Init subsystems
        client = BinanceClient(settings, session)
        telegram = TelegramBot(settings)
        await telegram.open()
        telegram.set_callbacks(
            get_status=get_status,
            get_balance=get_balance,
            shutdown=do_shutdown,
            simulate=simulate_signal,
        )

        # Start polling immediately so /start etc. respond during bootstrap
        polling_task = asyncio.create_task(telegram.start_polling(), name="telegram")

        # Load symbol precision info (needed for order rounding)
        await client.load_symbol_info(*settings.symbol_list)

        # Bootstrap candle buffers for each symbol
        all_streams: list[str] = []

        for sym in settings.symbol_list:
            buf = KlineBuffers(sym, on_candle_close=on_candle_close)
            buf.register_interval("4h", max_len=25)
            buf.register_interval("5m", max_len=10)

            await buf.bootstrap(client, "4h", limit=20)
            await buf.bootstrap(client, "5m", limit=3)

            buffers[sym] = buf
            states[sym] = EngineState(symbol=sym)
            all_streams.extend(buf.stream_names)

        log.info(f"Subscribing to streams: {all_streams}")

        # WebSocket
        ws = WSClient(
            ws_base=settings.binance_ws_base,
            streams=all_streams,
            on_message=on_ws_message,
        )

        # Launch tasks
        tasks = [
            asyncio.create_task(ws.start(session), name="ws"),
            polling_task,
            asyncio.create_task(shutdown_event.wait(), name="shutdown_wait"),
        ]

        # Wait for shutdown signal
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        # Cleanup
        log.info("Shutting down...")
        await ws.stop()
        await telegram.stop()
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        await telegram.send("Engine stopped. 🛑")
        await telegram.close()
        log.info("Shutdown complete.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    loop = asyncio.new_event_loop()

    def handle_signal(sig, frame):
        log.info(f"Received {sig}, initiating shutdown...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
