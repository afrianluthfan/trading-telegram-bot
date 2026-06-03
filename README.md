# Tele-Binance Trading Bot

A pure-Python, async-first quantitative engine that hunts a single, narrow setup
on Binance USD-M Futures: a **5-minute Fair Value Gap** that prints inside a
**4-hour Fibonacci Kill Box**, *and* is corroborated by a Smart Money / retail
divergence on positioning data. When all three line up, the engine fires a
post-only bracket order (entry + stop-loss + take-profit) and reports the whole
flow to a Telegram control channel.

Defaults are wired for the Binance Futures **testnet**. Going live is a one-line
env change — read the warnings before you do it.

---

## Strategy in one paragraph

A 20-bar 4H high/low defines a macro range. The 0.618–0.786 retrace zones at the
top and bottom of that range are the **Kill Box** — the only places we will
consider entering. On every closed 5m candle we check whether price is inside
one of those zones; if it is, we look at the last three 5m candles for a Fair
Value Gap (a three-bar imbalance pointing in the same direction as the zone).
A matching FVG produces a *signal*, not a trade. Before a trade actually goes
out we hit three REST endpoints (top-trader L/S, retail L/S, open interest) and
require an institutional vs. retail divergence with rising OI. Only then is the
bracket submitted, with a maker (GTX) entry and STOP_MARKET / TAKE_PROFIT_MARKET
exits. A configurable per-symbol cooldown blocks re-entries for the next N 5m
candles.

```
  4H candles ─► Kill Box (0.618 / 0.786 retraces)  ┐
                                                   ├─► Signal ─► Institutional filter ─► Bracket order
  5m candles ─► Fair Value Gap (3-bar imbalance)   ┘                                       (entry + SL + TP)
```

---

## Repository layout

```
trading-telegram-bot/
├── pyproject.toml             # uv project; entry point: trading-telegram-bot = src.main:main
├── .env.example               # copy to .env, fill in keys
├── refs/                      # design docs (business logic, infra, WS streams, PDF)
├── DELAY_ANALYSIS.txt         # latency notes
├── src/
│   ├── config.py              # pydantic-settings: env vars + derived helpers
│   ├── main.py                # boot sequence, WS router, candle-close handler
│   ├── engine/
│   │   ├── models.py          # Candle, KillBox, FVG, Signal, BracketCoords, EngineState
│   │   ├── kill_box.py        # 20-bar 4H Fib zones
│   │   ├── fvg.py             # 3-candle Fair Value Gap detector
│   │   └── signal.py          # orchestrator: KillBox + FVG → Signal + bracket sizing
│   ├── filter/
│   │   └── institutional.py   # top L/S + retail L/S + OI divergence gate
│   ├── execution/
│   │   ├── client.py          # signed Binance Futures REST client, weight tracking
│   │   └── bracket.py         # GTX entry + STOP_MARKET SL + TAKE_PROFIT_MARKET TP
│   ├── ws/
│   │   ├── client.py          # combined-stream WS, auto-reconnect, 24h rotation
│   │   └── streams.py         # per-symbol kline buffers (REST bootstrap + live)
│   └── telegram/
│       └── bot.py             # long-poll bot: /start /status /balance /kill /simulate
└── tests/
    ├── test_kill_box.py
    ├── test_fvg.py
    └── test_bracket.py
```

---

## Requirements

- Python **3.11+** (see `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management (recommended)
- A Binance Futures account — **testnet** for development, mainnet only when you
  have read every line of `src/execution/`
- A Telegram bot token and chat ID (optional, but the simulate / kill commands
  go through it)

Runtime dependencies are intentionally minimal: `aiohttp` (HTTP + WebSocket) and
`pydantic-settings` (env loading). No exchange SDK, no pandas, no numpy.

---

## Setup

```bash
# 1. Install deps
uv sync

# 2. Configure credentials
cp .env.example .env
$EDITOR .env          # fill in your own keys — see "Configuration" below

# 3. Sanity check
uv run pytest

# 4. Run on testnet
uv run trading-telegram-bot
# or, pointing at a non-default env file:
uv run trading-telegram-bot .env-live
```

The `trading-telegram-bot` script is declared in `pyproject.toml` and resolves to
`src.main:main`.

---

## Configuration

All configuration is environment-based and validated by `src/config.py`. Copy
`.env.example` to `.env` and replace every value — the example file ships with
placeholder keys for demonstration, not for use.

| Variable                    | Default                                  | Meaning                                                |
| --------------------------- | ---------------------------------------- | ------------------------------------------------------ |
| `BINANCE_API_KEY`           | *(required)*                             | Futures API key                                        |
| `BINANCE_API_SECRET`        | *(required)*                             | Futures API secret                                     |
| `BINANCE_API_BASE`          | `https://testnet.binancefuture.com`      | Switch to `https://fapi.binance.com` for **live**      |
| `BINANCE_WS_BASE`           | `wss://stream.binancefuture.com`         | Switch to `wss://fstream.binance.com` for **live**     |
| `TELEGRAM_BOT_TOKEN`        | *(optional)*                             | Empty disables the bot                                 |
| `TELEGRAM_CHAT_ID`          | `0`                                      | Chat that receives notifications                       |
| `SYMBOLS`                   | `BTCUSDT`                                | Comma-separated symbols to monitor                     |
| `MARGIN_CAP`                | `1000`                                   | USDT margin per trade                                  |
| `LEVERAGE`                  | `100`                                    | Requested leverage (clamped by tier table)             |
| `SL_DELTA`                  | `0.0015`                                 | Stop distance from entry (15 bps)                      |
| `LONG_RETAIL_LS_MAX`        | `1.0`                                    | Retail L/S must be **below** this for a long           |
| `LONG_TOP_LS_MIN`           | `1.5`                                    | Top-trader L/S must be **above** this for a long       |
| `SHORT_RETAIL_LS_MIN`       | `1.5`                                    | Retail L/S must be **above** this for a short          |
| `SHORT_TOP_LS_MAX`          | `0.8`                                    | Top-trader L/S must be **below** this for a short      |
| `POST_TRADE_COOLDOWN`       | `3`                                      | 5m candles to skip after a trade                       |
| `API_WEIGHT_PAUSE_THRESHOLD`| `1800`                                   | When `X-MBX-USED-WEIGHT-1M` exceeds this, pause checks |

`Settings.is_testnet` is derived from whether `BINANCE_API_BASE` contains the
string `testnet`. The Telegram bot prefixes every message with `[TESTNET]` in
that mode — if you stop seeing the prefix, you are live.

---

## How a trade is born

`src/main.py` wires five subsystems together. The hot path is:

1. **WebSocket** (`src/ws/client.py`) subscribes to combined streams
   `{sym}@kline_4h` and `{sym}@kline_5m` for every symbol. The connection
   auto-reconnects, uses aiohttp heartbeats for ping/pong, and proactively
   rotates after ~23h50m to stay ahead of Binance's 24h cutoff.
2. **Buffers** (`src/ws/streams.py`) keep rolling deques of closed candles
   (20 × 4H, ~10 × 5m). At startup they are bootstrapped from
   `/fapi/v1/klines`; afterwards they advance one candle at a time as
   `k.x = true` messages arrive.
3. **Candle close handler** (`src/main.py::on_candle_close`) only acts on
   closed 5m candles. It calls `evaluate_signal`, which:
    - recomputes the **Kill Box** from the 20-bar 4H window
       (`src/engine/kill_box.py`),
    - checks the cooldown counter,
    - confirms the current 5m close sits inside the long or short zone,
    - asks `detect_fvg` (`src/engine/fvg.py`) whether the last three 5m candles
       form an imbalance pointing the same way.
4. If a signal pops out, `compute_bracket` sizes the position. Notional is
   `margin_cap × leverage`, clamped down by the testnet leverage-tier table in
   `src/engine/signal.py`. Stop is `entry × (1 ± SL_DELTA)`; take-profit is the
   0.382 retrace of the macro range back toward the opposite extreme.
5. **Institutional filter** (`src/filter/institutional.py`) issues three REST
   reads in parallel (top L/S, retail L/S, OI history). The trade is only
   authorized when retail and top-traders disagree *and* open interest is rising.
6. **Bracket execution** (`src/execution/bracket.py`):
    - Sets leverage on the symbol,
    - Rounds prices to `PRICE_FILTER.tickSize` and qty to `LOT_SIZE.stepSize`
       using the precision loaded from `/fapi/v1/exchangeInfo`,
    - Submits a `LIMIT` entry with `timeInForce=GTX` (post-only, guaranteed
       maker) on `/fapi/v1/order`,
    - Submits SL and TP as conditional algo orders
       (`STOP_MARKET` / `TAKE_PROFIT_MARKET`) on `/fapi/v1/algoOrder`,
    - `positionSide` is set explicitly, so the engine is hedge-mode safe.
7. **Cooldown + state** (`src/engine/models.py::EngineState`) marks the symbol
   as in position and ticks the cooldown counter down on subsequent closes.

Every Binance response is inspected for the `X-MBX-USED-WEIGHT-1M` header. When
the used weight crosses `API_WEIGHT_PAUSE_THRESHOLD`, the institutional filter
short-circuits and refuses to authorize trades until weight recovers — that
keeps the bot well clear of 429s and the 418 IP ban.

---

## Telegram control

If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, the bot long-polls
`getUpdates` and accepts:

| Command     | Effect                                                                |
| ----------- | --------------------------------------------------------------------- |
| `/start`    | Health probe — replies with a heartbeat                               |
| `/status`   | Per-symbol price, Kill Box zones, active zone, cooldown, position     |
| `/balance`  | USDT balance + available margin                                       |
| `/kill`     | Sets the shutdown event — engine drains and exits cleanly             |
| `/simulate` | Builds a synthetic LONG signal at 0.998× the current price and runs the full pipeline (filter → leverage → cancel/close → bracket). Useful for verifying connectivity and order routing on testnet without waiting for an actual setup. |

Signal, execution, abort, and error notifications all go to `TELEGRAM_CHAT_ID`
automatically. Outgoing IPv6 to `api.telegram.org` is disabled in the client
because many VPS providers have broken AAAA paths to Telegram.

---

## Testing

```bash
uv run pytest
```

The suite covers the deterministic units:

- `tests/test_kill_box.py` — Fibonacci zone math from a synthetic 4H buffer
- `tests/test_fvg.py` — bullish / bearish FVG detection across edge cases
- `tests/test_bracket.py` — bracket sizing, rounding, side / positionSide
   selection

Tests are pure CPU and don't touch the network.

---

## Going live — read before you flip the switch

1. Change `BINANCE_API_BASE` to `https://fapi.binance.com` and `BINANCE_WS_BASE`
   to `wss://fstream.binance.com`. The `[TESTNET]` prefix on Telegram messages
   will disappear — that's your signal that you are actually risking money.
2. The leverage-tier table in `src/engine/signal.py` is set for testnet caps.
   Mainnet tiers differ by symbol and by your account's risk class — verify
   against your actual exchange info before trusting the auto-clamp.
3. `MARGIN_CAP` is interpreted as USDT per trade. With `LEVERAGE=100` the
   default config will push **100,000 USDT of notional**. Start much smaller.
4. The bracket places an entry, an SL, and a TP as three separate orders. None
   of them are linked at the exchange — if the process dies between the entry
   filling and the SL/TP arriving, the position is unprotected. Run the engine
   under a supervisor (systemd, tmux + autorestart, etc.) and consider the
   `/kill` command your manual circuit breaker.
5. `.env` is gitignored. Do not commit credentials, do not paste them into
   issues, do not share them through screenshots.

---

## Background references

The `refs/` directory contains the source material this implementation was
derived from:

- `Python Quantitative Engine Sniper Entry.pdf` — the original spec
- `business-logic.md` — long-form description of the strategy
- `infra.md` — deployment / infrastructure notes
- `binance-websocket-streams.md` — relevant Binance stream documentation

`DELAY_ANALYSIS.txt` at the repo root captures end-to-end latency observations
from real runs.

---

## License

No license file is included. Treat this as private / all-rights-reserved unless
you add one.
