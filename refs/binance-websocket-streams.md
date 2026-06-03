# WebSocket Streams for Binance

> Source: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams

---

## General WSS Information

- The base endpoint is: **`wss://stream.binance.com:9443`** or **`wss://stream.binance.com:443`**
- Streams can be accessed either in a single raw stream or in a combined stream.
  - Raw streams are accessed at `/ws/<streamName>`
  - Combined streams are accessed at `/stream?streams=<streamName1>/<streamName2>/<streamName3>`
  - Combined stream events are wrapped as: `{"stream":"<streamName>","data":<rawPayload>}`
- All symbols for streams are **lowercase**
- A single connection to `stream.binance.com` is only valid for **24 hours**; expect to be disconnected at the 24-hour mark
- The WebSocket server will send a `ping frame` every 20 seconds.
  - If no `pong frame` is received within a minute, the connection will be disconnected.
  - When you receive a ping, you must send a pong with a copy of ping's payload as soon as possible.
  - Unsolicited `pong frames` are allowed but will not prevent disconnection. **It is recommended that the payload for these pong frames are empty.**
- The base endpoint **`wss://data-stream.binance.vision`** can be subscribed to receive **only** market data messages. User Data Stream is **NOT** available from this URL.
- All time and timestamp related fields are **milliseconds by default**. To receive information in microseconds, add the parameter `timeUnit=MICROSECOND` or `timeUnit=microsecond` in the URL.
  - Example: `/stream?streams=btcusdt@trade&timeUnit=MICROSECOND`
- If your request contains a symbol name with non-ASCII characters, stream events may contain non-ASCII characters encoded in UTF-8.

---

## WebSocket Limits

- WebSocket connections have a limit of **5 incoming messages per second**. A message is considered:
  - A PING frame
  - A PONG frame
  - A JSON controlled message (e.g. subscribe, unsubscribe)
- A connection that goes beyond the limit will be disconnected; IPs that are repeatedly disconnected may be banned.
- A single connection can listen to a maximum of **1024 streams**.
- There is a limit of **300 connections per attempt every 5 minutes per IP**.

---

## Live Subscribing/Unsubscribing to Streams

The `id` field is used as an identifier to uniquely identify messages. Accepted formats:
- 64-bit signed integer
- Alphanumeric strings (max length 36)
- `null`

If the `result` received is `null`, the request was successful (for non-query requests).

### Subscribe to a Stream

**Request:**
```json
{
    "method": "SUBSCRIBE",
    "params": ["btcusdt@aggTrade", "btcusdt@depth"],
    "id": 1
}
```

**Response:**
```json
{
    "result": null,
    "id": 1
}
```

### Unsubscribe to a Stream

**Request:**
```json
{
    "method": "UNSUBSCRIBE",
    "params": ["btcusdt@depth"],
    "id": 312
}
```

**Response:**
```json
{
    "result": null,
    "id": 312
}
```

### Listing Subscriptions

**Request:**
```json
{
    "method": "LIST_SUBSCRIPTIONS",
    "id": 3
}
```

**Response:**
```json
{
    "result": ["btcusdt@aggTrade"],
    "id": 3
}
```

### Setting Properties

Currently, the only settable property is whether `combined` stream payloads are enabled. It is `false` when connecting via `/ws/` (raw streams) and `true` when connecting via `/stream/`.

**Request:**
```json
{
    "method": "SET_PROPERTY",
    "params": ["combined", true],
    "id": 5
}
```

**Response:**
```json
{
    "result": null,
    "id": 5
}
```

### Retrieving Properties

**Request:**
```json
{
    "method": "GET_PROPERTY",
    "params": ["combined"],
    "id": 2
}
```

**Response:**
```json
{
    "result": true,
    "id": 2
}
```

### Error Messages

| Error Message | Description |
|---|---|
| `{"code": 0, "msg": "Unknown property","id": %s}` | Parameter used in `SET_PROPERTY` or `GET_PROPERTY` was invalid |
| `{"code": 1, "msg": "Invalid value type: expected Boolean"}` | Value should only be `true` or `false` |
| `{"code": 2, "msg": "Invalid request: property name must be a string"}` | Property name provided was invalid |
| `{"code": 2, "msg": "Invalid request: request ID must be an unsigned integer"}` | `id` parameter was missing or an unsupported type |
| `{"code": 2, "msg": "Invalid request: unknown variant %s, expected one of `SUBSCRIBE`, `UNSUBSCRIBE`, `LIST_SUBSCRIPTIONS`, `SET_PROPERTY`, `GET_PROPERTY` at line 1 column 28"}` | Possible typo in method or method was not one of the expected values |
| `{"code": 2, "msg": "Invalid request: too many parameters"}` | Unnecessary parameters provided |
| `{"code": 2, "msg": "Invalid request: missing field `method` at line 1 column 73"}` | `method` was not provided |
| `{"code":3,"msg":"Invalid JSON: expected value at line %s column %s"}` | JSON data sent has incorrect syntax |

---

## Detailed Stream Information

### Aggregate Trade Streams

Pushes trade information aggregated for a single taker order.

- **Stream Name:** `<symbol>@aggTrade`
- **Update Speed:** Real-time

**Payload:**
```json
{
    "e": "aggTrade",        // Event type
    "E": 1672515782136,     // Event time
    "s": "BNBBTC",          // Symbol
    "a": 12345,             // Aggregate trade ID
    "p": "0.001",           // Price
    "q": "100",             // Quantity
    "f": 100,               // First trade ID
    "l": 105,               // Last trade ID
    "T": 1672515782136,     // Trade time
    "m": true,              // Is the buyer the market maker?
    "M": true               // Ignore
}
```

---

### Trade Streams

Pushes raw trade information; each trade has a unique buyer and seller.

- **Stream Name:** `<symbol>@trade`
- **Update Speed:** Real-time

**Payload:**
```json
{
    "e": "trade",           // Event type
    "E": 1672515782136,     // Event time
    "s": "BNBBTC",          // Symbol
    "t": 12345,             // Trade ID
    "p": "0.001",           // Price
    "q": "100",             // Quantity
    "T": 1672515782136,     // Trade time
    "m": true,              // Is the buyer the market maker?
    "M": true               // Ignore
}
```

---

### Kline/Candlestick Streams for UTC

Pushes updates to the current klines/candlestick every second in `UTC+0` timezone.

**Supported intervals:** `1s`, `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `8h`, `12h`, `1d`, `3d`, `1w`, `1M`

- **Stream Name:** `<symbol>@kline_<interval>`
- **Update Speed:** 1000ms for `1s`, 2000ms for other intervals

**Payload:**
```json
{
    "e": "kline",               // Event type
    "E": 1672515782136,         // Event time
    "s": "BNBBTC",              // Symbol
    "k": {
        "t": 1672515780000,     // Kline start time
        "T": 1672515839999,     // Kline close time
        "s": "BNBBTC",          // Symbol
        "i": "1m",              // Interval
        "f": 100,               // First trade ID
        "L": 200,               // Last trade ID
        "o": "0.0010",          // Open price
        "c": "0.0020",          // Close price
        "h": "0.0025",          // High price
        "l": "0.0015",          // Low price
        "v": "1000",            // Base asset volume
        "n": 100,               // Number of trades
        "x": false,             // Is this kline closed?
        "q": "1.0000",          // Quote asset volume
        "V": "500",             // Taker buy base asset volume
        "Q": "0.500",           // Taker buy quote asset volume
        "B": "123456"           // Ignore
    }
}
```

---

### Kline/Candlestick Streams with Timezone Offset

Pushes updates to the current klines/candlestick every second in `UTC+8` timezone.

- Kline intervals open and close in the `UTC+8` timezone (e.g., `1d` klines open/close at `UTC+8` day boundaries).
- Note: `E` (event time), `t` (start time) and `T` (close time) in the payload are Unix timestamps, always interpreted in UTC.

- **Stream Name:** `<symbol>@kline_<interval>@+08:00`
- **Update Speed:** 1000ms for `1s`, 2000ms for other intervals

**Payload:** Same structure as UTC Kline payload above.

---

### Individual Symbol Mini Ticker Stream

24hr rolling window mini-ticker statistics (not UTC day statistics).

- **Stream Name:** `<symbol>@miniTicker`
- **Update Speed:** 1000ms

**Payload:**
```json
{
    "e": "24hrMiniTicker",     // Event type
    "E": 1672515782136,        // Event time
    "s": "BNBBTC",             // Symbol
    "c": "0.0025",             // Close price
    "o": "0.0010",             // Open price
    "h": "0.0025",             // High price
    "l": "0.0010",             // Low price
    "v": "10000",              // Total traded base asset volume
    "q": "18"                  // Total traded quote asset volume
}
```

---

### All Market Mini Tickers Stream

24hr rolling window mini-ticker statistics for all symbols that changed. Only tickers that have changed will be present in the array.

- **Stream Name:** `!miniTicker@arr`
- **Update Speed:** 1000ms

**Payload:**
```json
[
    {
        // Same as <symbol>@miniTicker payload
    }
]
```

---

### Individual Symbol Ticker Streams

24hr rolling window ticker statistics for a single symbol (not UTC day statistics).

- **Stream Name:** `<symbol>@ticker`
- **Update Speed:** 1000ms

**Payload:**
```json
{
    "e": "24hrTicker",      // Event type
    "E": 1672515782136,     // Event time
    "s": "BNBBTC",          // Symbol
    "p": "0.0015",          // Price change
    "P": "250.00",          // Price change percent
    "w": "0.0018",          // Weighted average price
    "x": "0.0009",          // First trade(F)-1 price (first trade before the 24hr rolling window)
    "c": "0.0025",          // Last price
    "Q": "10",              // Last quantity
    "b": "0.0024",          // Best bid price
    "B": "10",              // Best bid quantity
    "a": "0.0026",          // Best ask price
    "A": "100",             // Best ask quantity
    "o": "0.0010",          // Open price
    "h": "0.0025",          // High price
    "l": "0.0010",          // Low price
    "v": "10000",           // Total traded base asset volume
    "q": "18",              // Total traded quote asset volume
    "O": 0,                 // Statistics open time
    "C": 86400000,          // Statistics close time
    "F": 0,                 // First trade ID
    "L": 18150,             // Last trade Id
    "n": 18151              // Total number of trades
}
```

---

### Individual Symbol Rolling Window Statistics Streams

Rolling window ticker statistics for a single symbol, computed over multiple windows.

- **Stream Name:** `<symbol>@ticker_<window_size>`
- **Window Sizes:** `1h`, `4h`, `1d`
- **Update Speed:** 1000ms

> **Note:** The open time `"O"` always starts on a minute, while the closing time `"C"` is the current time of the update. The effective window might be up to 59999ms wider than `<window_size>`.

**Payload:**
```json
{
    "e": "1hTicker",        // Event type
    "E": 1672515782136,     // Event time
    "s": "BNBBTC",          // Symbol
    "p": "0.0015",          // Price change
    "P": "250.00",          // Price change percent
    "o": "0.0010",          // Open price
    "h": "0.0025",          // High price
    "l": "0.0010",          // Low price
    "c": "0.0025",          // Last price
    "w": "0.0018",          // Weighted average price
    "v": "10000",           // Total traded base asset volume
    "q": "18",              // Total traded quote asset volume
    "O": 0,                 // Statistics open time
    "C": 1675216573749,     // Statistics close time
    "F": 0,                 // First trade ID
    "L": 18150,             // Last trade Id
    "n": 18151              // Total number of trades
}
```

---

### All Market Rolling Window Statistics Streams

Rolling window ticker statistics for all market symbols, computed over multiple windows. Only tickers that have changed will be present in the array.

- **Stream Name:** `!ticker_<window-size>@arr`
- **Window Size:** `1h`, `4h`, `1d`
- **Update Speed:** 1000ms

**Payload:**
```json
[
    {
        // Same as <symbol>@ticker_<window_size> payload,
        // one for each symbol updated within the interval.
    }
]
```

---

### Individual Symbol Book Ticker Streams

Pushes any update to the best bid or ask's price or quantity in real-time. Multiple `<symbol>@bookTicker` streams can be subscribed to over one connection.

- **Stream Name:** `<symbol>@bookTicker`
- **Update Speed:** Real-time

**Payload:**
```json
{
    "u": 400900217,         // order book updateId
    "s": "BNBUSDT",         // symbol
    "b": "25.35190000",     // best bid price
    "B": "31.21000000",     // best bid qty
    "a": "25.36520000",     // best ask price
    "A": "40.66000000"      // best ask qty
}
```

---

### Average Price

Pushes changes in the average price over a fixed time interval.

- **Stream Name:** `<symbol>@avgPrice`
- **Update Speed:** 1000ms

**Payload:**
```json
{
    "e": "avgPrice",           // Event type
    "E": 1693907033000,        // Event time
    "s": "BTCUSDT",            // Symbol
    "i": "5m",                 // Average price interval
    "w": "25776.86000000",     // Average price
    "T": 1693907032213         // Last trade time
}
```

---

### Partial Book Depth Streams

Top `<levels>` bids and asks, pushed every second. Valid levels are `5`, `10`, or `20`.

- **Stream Names:** `<symbol>@depth<levels>` OR `<symbol>@depth<levels>@100ms`
- **Update Speed:** 1000ms or 100ms

**Payload:**
```json
{
    "lastUpdateId": 160,     // Last update ID
    "bids": [                // Bids to be updated
        [
            "0.0024",        // Price level to be updated
            "10"             // Quantity
        ]
    ],
    "asks": [                // Asks to be updated
        [
            "0.0026",        // Price level to be updated
            "100"            // Quantity
        ]
    ]
}
```

---

### Diff. Depth Stream

Order book price and quantity depth updates used to locally manage an order book.

- **Stream Name:** `<symbol>@depth` OR `<symbol>@depth@100ms`
- **Update Speed:** 1000ms or 100ms

**Payload:**
```json
{
    "e": "depthUpdate",     // Event type
    "E": 1672515782136,     // Event time
    "s": "BNBBTC",          // Symbol
    "U": 157,               // First update ID in event
    "u": 160,               // Final update ID in event
    "b": [                  // Bids to be updated
        [
            "0.0024",       // Price level to be updated
            "10"            // Quantity
        ]
    ],
    "a": [                  // Asks to be updated
        [
            "0.0026",       // Price level to be updated
            "100"           // Quantity
        ]
    ]
}
```

---

## How to Manage a Local Order Book Correctly

**Setup steps:**

1. Open a WebSocket connection to `wss://stream.binance.com:9443/ws/bnbbtc@depth`.
2. Buffer the events received from the stream. Note the `U` of the first event received.
3. Get a depth snapshot from `https://api.binance.com/api/v3/depth?symbol=BNBBTC&limit=5000`.
4. If the `lastUpdateId` from the snapshot is strictly less than the `U` from step 2, go back to step 3.
5. In the buffered events, discard any event where `u` is `<=` `lastUpdateId` of the snapshot. The first buffered event should now have `lastUpdateId` within its `[U;u]` range.
6. Set your local order book to the snapshot. Its update ID is `lastUpdateId`.
7. Apply the update procedure below to all buffered events, and then to all subsequent events received.

**Update procedure for each event:**

1. Decide whether the update event can be applied:
   - If the event last update ID (`u`) is less than the update ID of your local order book, **ignore the event**.
   - If the event first update ID (`U`) is greater than the local order book update ID + 1, **you have missed some events** — discard your local order book and restart from the beginning.
   - Normally, `U` of the next event equals `u + 1` of the previous event.
2. For each price level in bids (`b`) and asks (`a`), set the new quantity in the order book:
   - If the price level does not exist, **insert it** with the new quantity.
   - If the quantity is zero, **remove** the price level from the order book.
3. Set the order book update ID to the last update ID (`u`) in the processed event.

> **Note:** Depth snapshots from the API are limited to 5000 price levels per side. Quantities for levels outside the initial snapshot won't be known unless they change. For most use cases, 5000 levels per side is sufficient to understand the market and trade effectively.

---

*Copyright © 2026 Binance.*
