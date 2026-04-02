# Phase 2: Market Data & Analytics - Research

**Researched:** 2026-04-02
**Domain:** IB market data streaming, Redis distribution, IV analytics, earnings calendar
**Confidence:** HIGH

## Summary

This phase builds the real-time data infrastructure that downstream risk engine and agent pipeline depend on. The core pattern is: subscribe to IB market data via `ib_async.IB.reqMktData()`, receive streaming tick updates via `pendingTickersEvent` / `ticker.updateEvent`, distribute via Redis pub/sub channels, and persist time-series data to TimescaleDB hypertables.

The ib_async library (v2.1.0, already installed) provides everything needed for real-time quotes, Greeks, and IV streaming. The `Ticker` dataclass has `bidGreeks`, `askGreeks`, `lastGreeks`, `modelGreeks` attributes (each an `OptionComputation` with `impliedVol`, `delta`, `gamma`, `vega`, `theta`, `undPrice`), plus `openInterest`, `putOpenInterest`, `callOpenInterest`, `putVolume`, `callVolume`, and `impliedVolatility` for aggregate IV on the underlying. IB provides Greeks automatically when you subscribe to an option contract (provided you also have the underlying subscribed), so no external Greeks library is needed.

For IV rank/percentile, IB supports `reqHistoricalData()` with `whatToShow='OPTION_IMPLIED_VOLATILITY'` on STK and IND contracts (not OPT contracts). This provides daily IV bars going back up to 1 year, which is sufficient for 52-week IV rank/percentile calculation. For earnings calendar, the recommended approach is to use Finnhub's free-tier earnings calendar API -- IB's Wall Street Horizon data requires an expensive subscription, and yfinance's earnings scraping is unreliable.

**Primary recommendation:** Use IB's built-in streaming Greeks (no external volatility library needed), IB historical data for IV rank/percentile bootstrap, Redis pub/sub for real-time distribution with Redis HSET for latest-value cache, TimescaleDB hypertables for persistence, and Finnhub free API for earnings dates.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ib_async | 2.1.0 | Market data streaming, Greeks, IV | Already installed; provides reqMktData, Ticker, OptionComputation |
| redis[hiredis] | 7.4.0+ | Pub/sub distribution + latest-value cache | Already installed; async pub/sub + HSET for cache |
| sqlalchemy[asyncio] | 2.0.48+ | TimescaleDB persistence ORM | Already installed; Phase 1 pattern established |
| asyncpg | 0.31.0+ | Async PostgreSQL driver | Already installed; used with SQLAlchemy |
| structlog | 25.5.0+ | Structured logging | Already installed; Phase 1 pattern |
| pydantic | 2.12.5+ | Data models, validation, serialization | Already installed; for market data DTOs |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| finnhub-python | latest | Earnings calendar API | Plan 02-05: earnings date lookups |
| httpx | latest | Async HTTP client | Alternative to finnhub SDK for earnings API calls |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| IB built-in Greeks | py_vollib + scipy | IB provides Greeks for free via streaming; py_vollib is unmaintained (last release 2017) and would add unnecessary dependency |
| Finnhub earnings | yfinance | yfinance is scraping-based, unreliable (documented KeyError issues), no SLA |
| Finnhub earnings | IB Wall Street Horizon | Requires expensive paid subscription (Enchilada Pro), unnecessary for just earnings dates |
| Redis pub/sub | Redis Streams | Streams adds persistence/replay but we already persist to TimescaleDB; pub/sub has lower latency and simpler API for fire-and-forget distribution |
| Redis pub/sub | Redis Streams | If message loss during subscriber restart is unacceptable, Streams would be better -- but our TimescaleDB persistence already handles durability |

**Installation:**
```bash
uv add finnhub-python
```

## Architecture Patterns

### Recommended Project Structure
```
src/trading/
├── market_data/
│   ├── __init__.py
│   ├── manager.py          # MarketDataManager: subscription lifecycle, IB interaction
│   ├── distributor.py       # RedisDistributor: pub/sub publish + HSET cache
│   ├── subscriber.py        # SubscriptionManager: track active subs, enforce limits
│   ├── models.py            # Pydantic models for quotes, greeks, IV data
│   └── streamer.py          # Connects IB events to distributor (glue)
├── analytics/
│   ├── __init__.py
│   ├── iv_engine.py         # IV rank/percentile calculator
│   ├── iv_history.py        # Historical IV data fetching + storage
│   └── earnings.py          # Earnings calendar integration
├── db/
│   ├── models.py            # Add new TimescaleDB models for quotes, IV history
│   └── ...existing...
└── ...existing...
```

### Pattern 1: Event-Driven Tick Processing Pipeline
**What:** IB streams ticks into Ticker objects. We hook `pendingTickersEvent` or individual `ticker.updateEvent` to process updates, serialize to JSON, publish to Redis channels, and batch-write to TimescaleDB.
**When to use:** All real-time market data processing.
**Example:**
```python
# Source: ib_async installed source code (ib.py, ticker.py)

from ib_async import IB, Stock, Option
from trading.market_data.models import QuoteSnapshot, GreeksSnapshot

class MarketDataManager:
    def __init__(self, ib: IB, distributor: RedisDistributor):
        self.ib = ib
        self.distributor = distributor
        self._subscriptions: dict[int, Ticker] = {}  # conId -> Ticker

        # Hook the batch event for efficient processing
        self.ib.pendingTickersEvent += self._on_pending_tickers

    async def subscribe_underlying(self, symbol: str) -> Ticker:
        """Subscribe to underlying quotes + aggregate IV."""
        contract = Stock(symbol, "SMART", "USD")
        await self.ib.qualifyContractsAsync(contract)
        # genericTickList: 100=put/call volume, 101=OI, 106=impliedVol, 104=histVol
        ticker = self.ib.reqMktData(contract, genericTickList="100,101,104,106")
        self._subscriptions[contract.conId] = ticker
        return ticker

    async def subscribe_option(self, contract: Option) -> Ticker:
        """Subscribe to option quotes + Greeks.
        Greeks come automatically for options when underlying is also subscribed."""
        ticker = self.ib.reqMktData(contract, genericTickList="100,101")
        self._subscriptions[contract.conId] = ticker
        return ticker

    def _on_pending_tickers(self, tickers: set):
        """Called when any subscribed tickers have new data."""
        for ticker in tickers:
            if ticker.contract is None:
                continue
            # Publish quote data
            asyncio.create_task(self.distributor.publish_quote(ticker))
            # Publish Greeks if option
            if ticker.contract.secType == "OPT" and ticker.modelGreeks:
                asyncio.create_task(self.distributor.publish_greeks(ticker))
```

### Pattern 2: Redis Distribution (Pub/Sub + Latest-Value Cache)
**What:** Dual-layer distribution: pub/sub channels for streaming updates (downstream consumers subscribe), HSET for point-in-time latest-value queries (downstream consumers GET on demand).
**When to use:** Every market data update.
**Example:**
```python
# Source: redis.asyncio installed package, Redis docs

import json
from redis.asyncio import Redis

class RedisDistributor:
    # Channel naming convention
    QUOTE_CHANNEL = "mktdata:quote:{symbol}"
    GREEKS_CHANNEL = "mktdata:greeks:{symbol}:{conId}"
    QUOTE_HASH = "mktdata:latest:quote:{symbol}"
    GREEKS_HASH = "mktdata:latest:greeks:{conId}"

    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def publish_quote(self, ticker) -> None:
        """Publish quote snapshot to pub/sub and update latest-value cache."""
        symbol = ticker.contract.symbol
        data = {
            "symbol": symbol,
            "bid": float(ticker.bid) if not isnan(ticker.bid) else None,
            "ask": float(ticker.ask) if not isnan(ticker.ask) else None,
            "last": float(ticker.last) if not isnan(ticker.last) else None,
            "volume": float(ticker.volume) if not isnan(ticker.volume) else None,
            "timestamp": ticker.time.isoformat() if ticker.time else None,
        }
        payload = json.dumps(data)
        try:
            # Pub/sub for streaming consumers
            await self.redis.publish(
                self.QUOTE_CHANNEL.format(symbol=symbol), payload
            )
            # HSET for latest-value point queries
            await self.redis.hset(
                self.QUOTE_HASH.format(symbol=symbol), mapping=data
            )
        except Exception as e:
            # Cache errors are non-fatal (Phase 1 decision)
            logger.warning("redis.publish_failed", error=str(e))
```

### Pattern 3: Subscription Limit Management (100-line cap)
**What:** IB enforces 100 simultaneous market data lines per user. We need a subscription manager that tracks usage and handles limits.
**When to use:** Every subscribe/unsubscribe operation.
**Example:**
```python
class SubscriptionManager:
    MAX_LINES = 100
    # Reserve lines for open positions (always subscribed)
    RESERVED_LINES = 20

    def __init__(self, ib: IB):
        self.ib = ib
        self._active: dict[int, SubscriptionInfo] = {}  # conId -> info
        self._priority_pins: set[int] = set()  # conIds that cannot be evicted

    @property
    def available_lines(self) -> int:
        return self.MAX_LINES - len(self._active)

    async def subscribe(self, contract, priority: bool = False) -> Ticker | None:
        if contract.conId in self._active:
            return self._active[contract.conId].ticker

        if self.available_lines <= 0:
            # Evict lowest-priority, oldest subscription
            evicted = self._evict_one()
            if not evicted:
                logger.warning("subscription.limit_reached", active=len(self._active))
                return None

        ticker = self.ib.reqMktData(contract, genericTickList="100,101,104,106")
        self._active[contract.conId] = SubscriptionInfo(
            contract=contract, ticker=ticker, priority=priority,
            subscribed_at=datetime.utcnow()
        )
        if priority:
            self._priority_pins.add(contract.conId)
        return ticker

    def _evict_one(self) -> bool:
        """Evict the oldest non-priority subscription."""
        candidates = [
            (con_id, info) for con_id, info in self._active.items()
            if con_id not in self._priority_pins
        ]
        if not candidates:
            return False
        # Sort by subscribed_at, evict oldest
        candidates.sort(key=lambda x: x[1].subscribed_at)
        evict_id, evict_info = candidates[0]
        self.ib.cancelMktData(evict_info.contract)
        del self._active[evict_id]
        return True
```

### Pattern 4: TimescaleDB Batch Persistence
**What:** Buffer tick updates and batch-insert to TimescaleDB on a timer (e.g., every 5 seconds) rather than per-tick to avoid overwhelming the database.
**When to use:** All persistent storage of time-series data.
**Example:**
```python
class TimescaleDBWriter:
    FLUSH_INTERVAL = 5.0  # seconds
    BATCH_SIZE = 500

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._buffer: list[QuoteRecord] = []
        self._flush_task: asyncio.Task | None = None

    async def start(self):
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(self.FLUSH_INTERVAL)
            await self._flush()

    async def _flush(self):
        if not self._buffer:
            return
        batch, self._buffer = self._buffer[:self.BATCH_SIZE], self._buffer[self.BATCH_SIZE:]
        async with self._session_factory() as session:
            session.add_all(batch)
            await session.commit()
```

### Pattern 5: Staleness Detection (Timestamp-Based)
**What:** Track the last-update timestamp for each subscription. If a ticker hasn't updated in N seconds during market hours, mark it as stale. Publish staleness status on a dedicated channel.
**When to use:** Health monitoring of market data feeds.
**Example:**
```python
STALENESS_THRESHOLD = 30  # seconds without update = stale

class StalenessMonitor:
    def __init__(self, distributor: RedisDistributor):
        self._last_update: dict[int, float] = {}  # conId -> timestamp
        self._distributor = distributor

    def record_update(self, con_id: int):
        self._last_update[con_id] = time.time()

    async def check_staleness(self):
        """Called periodically (e.g., every 10 seconds)."""
        now = time.time()
        for con_id, last in self._last_update.items():
            if now - last > STALENESS_THRESHOLD:
                await self._distributor.publish_stale(con_id)
```

### Anti-Patterns to Avoid
- **Per-tick database writes:** Never write every tick individually to TimescaleDB. Buffer and batch-insert. IB can send hundreds of ticks/second across all subscriptions.
- **Subscribing to individual options without the underlying:** IB requires the underlying to also be subscribed for Greeks to populate on option tickers. Always subscribe underlying first.
- **Using reqTickByTickData for market data:** Limited to 3 simultaneous subscriptions. Use reqMktData instead (supports 100 lines).
- **Using snapshot (reqTickers) in a loop for "streaming":** Snapshots are one-shot and rate-limited. Use reqMktData for continuous streaming.
- **Storing raw NaN values in Redis/JSON:** ib_async Ticker fields default to NaN. Always check `math.isnan()` before serialization; JSON doesn't support NaN.
- **Creating new IB() instances:** The project uses a single IB() instance (Phase 1 decision). All market data subscriptions go through the same instance.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Options Greeks (delta/gamma/theta/vega) | Custom Black-Scholes calculator | IB's built-in Greeks via `ticker.modelGreeks` | IB calculates Greeks server-side using their proprietary model including dividend adjustments; custom implementations miss edge cases (American options, early exercise, dividend effects) |
| Implied volatility calculation | scipy Newton-Raphson solver | IB's `ticker.impliedVolatility` (underlying) and `ticker.modelGreeks.impliedVol` (per-option) | IB uses Peter Jackel's algorithm (same as py_vollib) server-side; no need for local computation |
| Historical IV for underlying | Scrape CBOE or calculate from option prices | `ib.reqHistoricalDataAsync(stock_contract, ..., whatToShow='OPTION_IMPLIED_VOLATILITY')` | IB provides daily IV bars for STK and IND contracts going back 1 year; reliable and free with data subscription |
| NaN handling in serialization | Custom JSON encoder | `math.isnan()` checks before serialization, replace with `None` | JSON spec doesn't support NaN; must filter before `json.dumps()` |
| Earnings date lookups | Scraping Yahoo Finance | Finnhub API (`/calendar/earnings` endpoint) | Free tier with 30 calls/sec, structured JSON response with date + before/after market indicator |

**Key insight:** IB is already computing Greeks, IV, open interest, and volume server-side. Our job is distribution and persistence, not computation. The only custom computation needed is IV rank/percentile from stored historical data.

## Common Pitfalls

### Pitfall 1: Forgetting to Subscribe Underlying Before Options
**What goes wrong:** Option tickers have `modelGreeks = None`, `bidGreeks = None` etc. Greeks never populate.
**Why it happens:** IB requires an active market data subscription on the underlying contract for the option Greeks to be calculated. This is a server-side requirement, not a library bug.
**How to avoid:** Always ensure the underlying (Stock/Index) is subscribed via `reqMktData()` before subscribing to its options. The SubscriptionManager should enforce this by auto-subscribing the underlying when an option subscription is requested.
**Warning signs:** `ticker.modelGreeks is None` after >5 seconds of subscription.

### Pitfall 2: Market Data Line Exhaustion
**What goes wrong:** New subscriptions silently fail or return error 354 ("Requested market data is not subscribed").
**Why it happens:** IB enforces a hard 100-line limit per user across ALL connections (TWS + API). If TWS watchlist has 50 symbols, API can only use 50 more.
**How to avoid:** Implement SubscriptionManager with line counting. Reserve lines for high-priority subscriptions (open positions). Implement LRU eviction for low-priority subscriptions. Log current usage on every subscribe/unsubscribe.
**Warning signs:** IB error code 354 or 100 in error callback.

### Pitfall 3: NaN Serialization Errors
**What goes wrong:** `json.dumps()` raises `ValueError` or produces invalid JSON with `NaN` tokens (not valid JSON per spec).
**Why it happens:** ib_async Ticker initializes all float fields to `float('nan')`. Before data arrives (first few seconds) or when market is closed, many fields remain NaN.
**How to avoid:** Create a serialization helper that converts NaN to None: `value if not math.isnan(value) else None`. Apply to every float field before JSON serialization.
**Warning signs:** `json.dumps` raising errors, downstream consumers crashing on invalid JSON.

### Pitfall 4: Historical IV Data Pacing Violations
**What goes wrong:** IB disconnects the API client, all market data subscriptions lost.
**Why it happens:** IB enforces strict pacing: max 60 historical data requests per 10-minute window, no identical requests within 15 seconds, max 6 requests for same contract/exchange/type within 2 seconds.
**How to avoid:** Implement a request queue with rate limiting for IV history bootstrap. Space requests at least 2 seconds apart. Cache results aggressively. Run the bootstrap during off-hours. Never request historical data in a tight loop.
**Warning signs:** IB error code 162 ("Historical data request pacing violation").

### Pitfall 5: Missing Market Data During Off-Hours
**What goes wrong:** System starts outside market hours, all tickers show NaN. Downstream systems that depend on "latest quotes" get no data.
**Why it happens:** IB does not stream real-time data outside Regular Trading Hours (RTH) for most products unless extended hours data is requested.
**How to avoid:** On startup, request a single snapshot of last closing prices. Store these in the latest-value Redis cache. Mark data as "closing" rather than "live". Only transition to live data when market opens.
**Warning signs:** All ticker fields showing NaN; no updates coming through `pendingTickersEvent`.

### Pitfall 6: OPTION_IMPLIED_VOLATILITY on Wrong Contract Type
**What goes wrong:** `reqHistoricalDataAsync()` returns empty bars or error 162 ("No historical market data").
**Why it happens:** `whatToShow='OPTION_IMPLIED_VOLATILITY'` only works on STK and IND contracts, NOT on OPT contracts. Requesting historical IV on an Option contract will fail.
**How to avoid:** Always use the underlying Stock or Index contract for historical IV requests. This returns the aggregate IV for that underlying, which is what you want for IV rank/percentile anyway.
**Warning signs:** Empty BarDataList returned, error code 162.

### Pitfall 7: Redis Pub/Sub Message Loss
**What goes wrong:** Downstream consumers miss market data updates.
**Why it happens:** Redis pub/sub is fire-and-forget. If a subscriber disconnects momentarily or is slow to consume, messages are dropped. There is no replay.
**How to avoid:** This is by design -- pub/sub is for real-time streaming only. For durability, we persist to TimescaleDB. For latest values, we cache in Redis HSET. Downstream consumers that need catch-up should query TimescaleDB, not rely on pub/sub replay. Document this contract clearly.
**Warning signs:** Consumer reports "gap" in data that doesn't appear in TimescaleDB.

## Code Examples

Verified patterns from official sources:

### Requesting Market Data with Generic Ticks
```python
# Source: ib_async/ib.py installed v2.1.0 - reqMktData docstring

# Generic tick IDs (from ib_async source):
# 100 = putVolume, callVolume
# 101 = putOpenInterest, callOpenInterest
# 104 = histVolatility
# 105 = avOptionVolume
# 106 = impliedVolatility
# 165 = low52week, high52week, avVolume
# 233 = last, lastSize, rtVolume, rtTime, vwap (Time & Sales)

# For underlying equities - get IV + OI + volume
ticker = ib.reqMktData(
    Stock("SPY", "SMART", "USD"),
    genericTickList="100,101,104,106,165",
)

# For option contracts - Greeks come automatically
# (101 for OI data; no need for 106 since IV comes via OptionComputation)
ticker = ib.reqMktData(
    Option("SPY", "20260417", 500, "C", "SMART"),
    genericTickList="100,101",
)
```

### Accessing Greeks from Ticker
```python
# Source: ib_async/objects.py - OptionComputation dataclass
# Source: ib_async/ticker.py - Ticker dataclass

# OptionComputation fields:
# tickAttrib: int
# impliedVol: float | None
# delta: float | None
# optPrice: float | None
# pvDividend: float | None
# gamma: float | None
# vega: float | None
# theta: float | None
# undPrice: float | None

# Access model Greeks (IB's own model, always populated when underlying subscribed)
if ticker.modelGreeks is not None:
    greeks = ticker.modelGreeks
    iv = greeks.impliedVol      # Per-contract IV
    delta = greeks.delta
    gamma = greeks.gamma
    theta = greeks.theta
    vega = greeks.vega
    und_price = greeks.undPrice  # Underlying price used in calculation

# Access bid/ask/last Greeks
if ticker.bidGreeks is not None:
    bid_iv = ticker.bidGreeks.impliedVol
    bid_delta = ticker.bidGreeks.delta

# Underlying aggregate IV (from generic tick 106)
underlying_iv = ticker.impliedVolatility  # float, NaN if unavailable

# Open interest (from generic tick 101)
put_oi = ticker.putOpenInterest
call_oi = ticker.callOpenInterest
```

### Historical IV Data for IV Rank/Percentile
```python
# Source: ib_async/ib.py - reqHistoricalData method
# CRITICAL: Use STK/IND contract, NOT OPT contract

bars = await ib.reqHistoricalDataAsync(
    contract=Stock("SPY", "SMART", "USD"),
    endDateTime="",           # current time
    durationStr="1 Y",        # 1 year of data
    barSizeSetting="1 day",   # daily bars
    whatToShow="OPTION_IMPLIED_VOLATILITY",
    useRTH=True,
    formatDate=1,
)
# bars is a BarDataList of BarData objects
# Each bar has: date, open, high, low, close, volume, average, barCount
# For IV data: close = closing IV value for that day
for bar in bars:
    date = bar.date
    iv_close = bar.close  # This is the IV value, not a price
```

### Redis Async Pub/Sub Consumer
```python
# Source: redis.asyncio installed package

import redis.asyncio as aioredis

async def consume_quotes(redis_url: str, symbol: str):
    """Example downstream consumer for market data."""
    client = aioredis.Redis.from_url(redis_url, decode_responses=True)
    async with client.pubsub() as pubsub:
        await pubsub.subscribe(f"mktdata:quote:{symbol}")
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                # Process quote: data has bid, ask, last, volume, timestamp
                process_quote(data)
```

### IV Rank and IV Percentile Calculation
```python
# IV Rank = (Current IV - 52-week Low IV) / (52-week High IV - 52-week Low IV)
# IV Percentile = % of days in past year where IV was lower than current

def calculate_iv_rank(current_iv: float, iv_history: list[float]) -> float:
    """IV Rank: position within the 52-week range."""
    if not iv_history:
        return 0.0
    low = min(iv_history)
    high = max(iv_history)
    if high == low:
        return 50.0  # No range, return midpoint
    return ((current_iv - low) / (high - low)) * 100.0

def calculate_iv_percentile(current_iv: float, iv_history: list[float]) -> float:
    """IV Percentile: % of days with IV below current."""
    if not iv_history:
        return 0.0
    below = sum(1 for iv in iv_history if iv < current_iv)
    return (below / len(iv_history)) * 100.0
```

### TimescaleDB Schema for Market Data
```python
# Follow Phase 1 pattern: raw SQL in Alembic migration for hypertable creation

# Migration upgrade():
op.create_table(
    "market_quotes",
    sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False,
              server_default=sa.func.now()),
    sa.Column("symbol", sa.String(20), nullable=False),
    sa.Column("bid", sa.Float, nullable=True),
    sa.Column("ask", sa.Float, nullable=True),
    sa.Column("last", sa.Float, nullable=True),
    sa.Column("volume", sa.Float, nullable=True),
    sa.Column("open_interest", sa.Float, nullable=True),
)
op.create_index("ix_market_quotes_symbol_ts", "market_quotes", ["symbol", "timestamp"])
op.execute("SELECT create_hypertable('market_quotes', 'timestamp')")

op.create_table(
    "iv_history",
    sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False,
              server_default=sa.func.now()),
    sa.Column("symbol", sa.String(20), nullable=False),
    sa.Column("iv_close", sa.Float, nullable=False),
    sa.Column("iv_high", sa.Float, nullable=True),
    sa.Column("iv_low", sa.Float, nullable=True),
    sa.Column("hv_close", sa.Float, nullable=True),  # historical volatility
)
op.create_index("ix_iv_history_symbol_ts", "iv_history", ["symbol", "timestamp"])
op.execute("SELECT create_hypertable('iv_history', 'timestamp')")
```

### Finnhub Earnings Calendar
```python
# Source: finnhub.io API docs

import finnhub

client = finnhub.Client(api_key="YOUR_KEY")

# Get earnings calendar for date range
earnings = client.earnings_calendar(
    _from="2026-04-01",
    to="2026-04-30",
    symbol="AAPL"
)
# Returns: {"earningsCalendar": [
#   {"date": "2026-04-28", "epsActual": None, "epsEstimate": 1.65,
#    "hour": "amc", "quarter": 2, "revenueActual": None,
#    "revenueEstimate": 94200000000, "symbol": "AAPL", "year": 2026}
# ]}
# "hour" field: "bmo" (before market open), "amc" (after market close), "dmh" (during market hours)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ib_insync | ib_async (fork) | 2023 | Drop-in replacement; actively maintained; same API surface |
| aioredis (separate package) | redis[hiredis] with redis.asyncio | redis-py 4.2+ (2022) | Unified package; aioredis is deprecated |
| py_vollib for Greeks | IB server-side Greeks via reqMktData | Always available | No external dependency needed; IB's model handles dividends, early exercise |
| reqFundamentalData for earnings | reqWshEventData (paid) or Finnhub | TWS v985+ | IB deprecated reqFundamentalData; WSH requires paid subscription |
| TimescaleDB manual partitioning | create_hypertable() automatic | TimescaleDB 2.0+ | Automatic chunk management; just call create_hypertable |

**Deprecated/outdated:**
- `ib_insync`: Replaced by `ib_async`. Same API, actively maintained.
- `aioredis` standalone: Merged into `redis-py` as `redis.asyncio`.
- `py_vollib`: Last release 2017. Pure Python, technically installs on 3.14 but unmaintained. Not needed since IB provides Greeks.
- `reqFundamentalData`: Marked as Legacy/DEPRECATED in IB API docs. Replaced by WSH event data (paid).

## Open Questions

Things that couldn't be fully resolved:

1. **Finnhub free tier rate limits**
   - What we know: 30 API calls/second is documented. Free tier exists.
   - What's unclear: Exact monthly call quota on free tier; whether earnings calendar endpoint has additional restrictions.
   - Recommendation: Start with Finnhub free tier. Call earnings calendar daily pre-market for all watchlist symbols. If rate limits hit, batch requests or consider $0/mo plan specifics. Fallback: yfinance `Ticker.calendar` as degraded backup.

2. **IB OPTION_IMPLIED_VOLATILITY historical data reliability**
   - What we know: Works for STK and IND contracts. Documented in IB API. Some users report sporadic Error 162 for certain symbols.
   - What's unclear: Whether all symbols have 1 year of history. Whether IB provides this for all subscription tiers.
   - Recommendation: Implement with graceful fallback. If IB returns empty data, log warning and start accumulating locally from day one. IV rank/percentile should degrade gracefully with less than 252 days of data (show "insufficient data" indicator).

3. **Off-hours subscription cost**
   - What we know: IB counts market data lines even during off-hours if subscriptions are active. Data doesn't stream outside RTH for most products.
   - What's unclear: Whether unsubscribing at close and re-subscribing at open causes reconnection overhead or missed data.
   - Recommendation: Keep subscriptions active during off-hours. The 100-line limit is the constraint, not per-line cost. Unsubscribing/resubscribing daily adds fragile scheduling logic for minimal benefit.

4. **Exact Python 3.14 compatibility of finnhub-python**
   - What we know: `uv add finnhub-python` should resolve. The library is a thin REST wrapper.
   - What's unclear: Whether it has been tested on 3.14 specifically.
   - Recommendation: Try installing. If issues, use `httpx` directly with Finnhub REST API (it's just GET requests with JSON responses).

## Architectural Decisions (Claude's Discretion Items)

Based on research, these are the recommended choices for the items delegated to Claude:

### Subscription Lifecycle: Hybrid Seed + Dynamic
- **Recommendation:** Start with a YAML-configured watchlist of underlyings (seed). Allow agents in later phases to request dynamic subscriptions. Subscription manager enforces the 100-line cap.
- **Rationale:** Pure static is too rigid for future phases. Pure dynamic means nothing works at startup. Hybrid gives immediate data flow with future extensibility.

### Subscription Limit Strategy: Priority-Based with LRU Eviction
- **Recommendation:** Priority levels: HIGH (open positions, always pinned), MEDIUM (watchlist underlyings), LOW (agent-requested, evictable). When at capacity, evict oldest LOW-priority subscription.
- **Rationale:** Open positions MUST always have data. Watchlist items are important but could be cycled. Agent requests are ephemeral.

### Subscription Scope: Underlyings Always, Options On-Demand
- **Recommendation:** Auto-subscribe all watchlist underlyings. Subscribe to specific option contracts only when an agent or downstream component requests Greeks for that contract. This conserves market data lines.
- **Rationale:** Each option contract = 1 data line. A single underlying with 20 expiries x 50 strikes x 2 rights = 2000 options. Cannot subscribe to all. Subscribe to specific strikes/expiries as needed.

### Off-Hours: Keep Subscriptions Active
- **Recommendation:** Leave subscriptions active 24/7. Do not unsubscribe at market close.
- **Rationale:** Simplicity. Subscription management is complex enough without daily cycling. Lines are already allocated. Some products have extended hours data.

### IV History Source: IB Historical Data + Local Accumulation
- **Recommendation:** Bootstrap with `reqHistoricalDataAsync(whatToShow='OPTION_IMPLIED_VOLATILITY')` for 1 year daily bars. Then accumulate locally by snapshotting current IV daily. Fall back to local-only if IB historical data unavailable for a symbol.
- **Rationale:** IB provides the data for free. No external dependency. Local accumulation ensures data availability over time even if IB gaps.

### Cold Start: Graceful Degradation
- **Recommendation:** When no IV history exists, report IV rank/percentile as `None` (not 0 or 50). Downstream consumers must handle `None` explicitly. Start accumulating immediately.
- **Rationale:** Returning a numeric guess is misleading. `None` forces downstream to acknowledge insufficient data.

### IV Storage Granularity: Daily Close
- **Recommendation:** Store one IV reading per day per symbol (end-of-day IV close from IB or snapshot at 3:55 PM ET). Not intraday.
- **Rationale:** IV rank/percentile is inherently a daily metric (52-week = 252 trading days). Intraday storage wastes space with no analytical benefit.

### IV Computation Strategy: Daily Cache + Intraday Refresh
- **Recommendation:** Compute IV rank/percentile once at market open using previous day's close. Refresh periodically (every 15 min) during market hours using the current live IV vs. stored history.
- **Rationale:** IV rank doesn't change dramatically intraday. Computing every tick is wasteful. But a stale morning value all day misses significant IV moves.

### Data Distribution: Redis Pub/Sub + HSET Latest-Value Cache
- **Recommendation:** Pub/sub for streaming, HSET for point queries, TimescaleDB for persistence. Triple-write from the distributor.
- **Rationale:** Different access patterns need different stores. Pub/sub for reactive agents. HSET for request/response queries. TimescaleDB for historical analysis and IV calculations.

### Staleness Detection: Timestamp-Based
- **Recommendation:** Track last-update timestamp per subscription. If no update in 30 seconds during RTH, mark stale. Publish staleness on a dedicated Redis channel (`mktdata:stale`).
- **Rationale:** Simple, reliable, no additional IB API calls. A 30-second threshold is generous enough to avoid false positives but catches genuine data feed issues.

### Earnings Calendar Source: Finnhub Free API
- **Recommendation:** Use Finnhub's `/calendar/earnings` endpoint. Refresh daily at 6:00 AM ET (pre-market). Cache results in Redis with 24-hour TTL and in TimescaleDB for history.
- **Rationale:** Free, structured API with before/after market indicator. No expensive IB subscription needed. More reliable than Yahoo scraping.

### Earnings Lookout Window: 7 Calendar Days
- **Recommendation:** Flag any underlying with earnings within 7 calendar days. Include metadata: `{date, days_until, hour: bmo|amc|dmh, eps_estimate}`.
- **Rationale:** 7 days captures the IV expansion window that matters for options strategies. Beyond 7 days, IV impact is minimal.

### Data Retention: 90 Days Raw Ticks, Unlimited Daily Aggregates
- **Recommendation:** Raw quote ticks in TimescaleDB: retain 90 days (use TimescaleDB retention policy). Daily IV history: retain indefinitely. Earnings data: retain indefinitely.
- **Rationale:** Tick-level data grows fast. 90 days is sufficient for backtesting recent strategies. Daily aggregates are small and valuable for long-term analytics.

## Sources

### Primary (HIGH confidence)
- ib_async v2.1.0 installed source code (`/Users/mobo/trading/.venv/lib/python3.14/site-packages/ib_async/`) - Ticker class, OptionComputation class, reqMktData signature with genericTickList, reqHistoricalData signature with whatToShow options
- IB TWS API Official Docs - [Option Computations](https://interactivebrokers.github.io/tws-api/option_computations.html) - Greeks via tick types 10/11/12/13
- IB TWS API Official Docs - [Available Tick Types](https://interactivebrokers.github.io/tws-api/tick_types.html) - tick IDs for OI, volume, IV
- IB TWS API Official Docs - [Historical Bar Data](https://interactivebrokers.github.io/tws-api/historical_bars.html) - whatToShow support matrix (OPTION_IMPLIED_VOLATILITY works for STK/IND)
- IB TWS API Official Docs - [Historical Limitations](https://interactivebrokers.github.io/tws-api/historical_limitations.html) - 60 requests/10min, 50 concurrent, pacing rules
- IB TWS API Official Docs - [Market Data Subscriptions](https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/) - 100 line limit

### Secondary (MEDIUM confidence)
- [Finnhub Earnings Calendar API](https://finnhub.io/docs/api/earnings-calendar) - endpoint structure, response format
- [ib_insync GitHub Issue #458](https://github.com/erdewit/ib_insync/issues/458) - confirmed OPTION_IMPLIED_VOLATILITY works on STK/IND, not OPT
- [Redis Pub/Sub vs Streams comparison](https://oneuptime.com/blog/post/2026-01-21-redis-streams-vs-pubsub/view) - tradeoffs for our use case
- py_vollib [PyPI](https://pypi.org/project/py-vollib/) - last release April 2017, not needed

### Tertiary (LOW confidence)
- yfinance earnings_dates reliability issues - multiple GitHub issues (#2143, #2123, #2559) suggest instability
- Finnhub free tier exact monthly quota - not found in docs, needs validation during implementation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - verified against installed ib_async source code, existing project dependencies, and IB official docs
- Architecture: HIGH - patterns derived from ib_async source code analysis and Phase 1 established patterns
- Pitfalls: HIGH - verified against IB API docs (subscription limits, pacing rules, contract type restrictions) and ib_async source code (NaN defaults, OptionComputation structure)
- IV rank/percentile approach: HIGH - IB historical IV bars verified in official whatToShow support matrix
- Earnings calendar: MEDIUM - Finnhub API docs verified but free tier limits not fully confirmed
- py_vollib status: HIGH - confirmed unmaintained (2017), confirmed unnecessary (IB provides Greeks)

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (30 days - stable domain, IB API rarely changes)
