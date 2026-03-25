# Phase 1: IB Connectivity & Infrastructure - Research

**Researched:** 2026-03-25
**Domain:** Interactive Brokers API connectivity, Python project infrastructure, database/cache setup
**Confidence:** HIGH

## Summary

Phase 1 establishes the foundational infrastructure for an autonomous options trading system: reliable IB Gateway connectivity, project scaffolding, database/cache layer, configuration system, order state tracking, and paper/live toggle. The research covers six interrelated domains that must work together.

The standard approach uses `ib_async` (v2.1.0, the actively maintained successor to `ib_insync`) for all IB API interactions, `gnzsnz/ib-gateway-docker` for containerized IB Gateway with paper/live mode switching via environment variable, PostgreSQL + TimescaleDB for time-series persistence, Redis for caching and pub/sub, SQLAlchemy 2.0 async + Alembic for ORM and migrations, `pydantic-settings` for type-safe configuration, and `transitions` or `python-statemachine` for the order state machine.

The project should use `uv` as the package manager with a single-package `src/` layout (not a monorepo workspace), since all domains ship as one deployable unit. Configuration uses a layered approach: YAML files for structured defaults, environment variables for deployment overrides, Docker secrets for sensitive values.

**Primary recommendation:** Use `ib_async` 2.1.0 with `gnzsnz/ib-gateway-docker`, PostgreSQL/TimescaleDB + Redis in Docker Compose, `pydantic-settings` with YAML + env var layering, and `python-statemachine` for order state tracking. Ship everything as a single Python package managed by `uv`.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `ib_async` | 2.1.0 | IB API client (connection, orders, contracts, market data) | Actively maintained successor to `ib_insync`; async-native; implements IBKR binary protocol directly; Python 3.10+ |
| `sqlalchemy[asyncio]` | 2.0+ | Async ORM for PostgreSQL | Industry standard Python ORM; native async support via asyncpg; type-safe query building |
| `asyncpg` | 0.30+ | Async PostgreSQL driver | Fastest Python PostgreSQL driver; required by SQLAlchemy async |
| `alembic` | 1.14+ | Database schema migrations | Only serious migration tool for SQLAlchemy; supports async via `--template async` |
| `redis[hiredis]` | 5.0+ | Async Redis client (cache, pub/sub) | Official `redis-py` now includes async support (aioredis merged in); hiredis for C-speed parsing |
| `pydantic-settings` | 2.7+ | Type-safe configuration from env vars, YAML, secrets | Part of Pydantic ecosystem; supports layered sources with priority ordering; validates all config at startup |
| `python-statemachine` | 3.0+ | Order state machine | Clean declarative API; auto-selects sync/async engine; run-to-completion model prevents race conditions |
| `pydantic` | 2.10+ | Data validation, serialization for contracts/orders/events | Foundation for all structured data; used by `ib_async` data classes and settings |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `uvicorn` | 0.34+ | ASGI server | Later phases (dashboard API), but install now for health check endpoint |
| `structlog` | 24.0+ | Structured JSON logging | All components; consistent log format for debugging connection issues, order tracking |
| `tenacity` | 9.0+ | Retry logic with backoff | Wrapping IB reconnection, database connection retries |
| `sqlalchemy-timescaledb` | 0.4+ | TimescaleDB dialect for SQLAlchemy | Hypertable creation via `__table_args__`; community-maintained but functional |
| `pyaml-env` | 1.2+ | YAML with env var interpolation | Config files that reference `${ENV_VAR}` |
| `python-dotenv` | 1.0+ | .env file loading for local dev | Development convenience; not used in production Docker |

### Infrastructure (Docker)

| Component | Image | Purpose | Configuration |
|-----------|-------|---------|---------------|
| IB Gateway | `ghcr.io/gnzsnz/ib-gateway:stable` | Containerized IB Gateway with IBC | `TRADING_MODE=paper\|live`, auto-restart, 2FA handling |
| PostgreSQL + TimescaleDB | `timescale/timescaledb:latest-pg16` | Time-series database | Hypertables for tick data, orders, state transitions |
| Redis | `redis:7-alpine` | Cache and pub/sub | Connection state, contract cache, event distribution |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ib_async` | `ibapi` (official IB Python API) | Official but callback-heavy, no async, painful to use; `ib_async` wraps the binary protocol directly |
| `ib_async` | `ib_insync` (original) | Original author passed away 2024; `ib_async` is the community continuation with active maintenance |
| `python-statemachine` | `transitions` (pytransitions) | `transitions` is more popular but `python-statemachine` has cleaner declarative API, automatic async engine, and run-to-completion guarantees |
| `pydantic-settings` | `dynaconf` | Dynaconf is powerful but adds another dependency outside Pydantic ecosystem; `pydantic-settings` integrates naturally with Pydantic models used everywhere |
| `sqlalchemy-timescaledb` | Raw SQL for hypertables | Raw SQL works fine for `SELECT create_hypertable(...)` but dialect lets you declare in model `__table_args__` |
| `uv` | `poetry` / `pip` | `uv` is 10-100x faster, handles lockfiles, Python version management; modern standard |

**Installation:**
```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Initialize project
uv init trading-system
cd trading-system

# Add core dependencies
uv add ib_async sqlalchemy[asyncio] asyncpg alembic "redis[hiredis]" pydantic-settings pydantic python-statemachine structlog tenacity sqlalchemy-timescaledb

# Add dev dependencies
uv add --dev pytest pytest-asyncio ruff mypy
```

## Architecture Patterns

### Recommended Project Structure
```
trading-system/
├── pyproject.toml              # uv project config, all dependencies
├── uv.lock                     # Locked dependency versions
├── docker-compose.yml          # IB Gateway, PostgreSQL/TimescaleDB, Redis
├── docker-compose.override.yml # Local dev overrides
├── config/
│   ├── default.yml             # Default configuration (committed)
│   ├── paper.yml               # Paper trading overrides (committed)
│   ├── live.yml                # Live trading overrides (committed, no secrets)
│   └── local.yml               # Local overrides (gitignored)
├── alembic/
│   ├── alembic.ini
│   ├── env.py                  # Async migration environment
│   └── versions/               # Migration files
├── src/
│   └── trading/
│       ├── __init__.py
│       ├── app.py              # Application entrypoint, lifecycle
│       ├── config.py           # Pydantic Settings classes
│       ├── core/
│       │   ├── __init__.py
│       │   ├── connection.py   # IB Gateway connection manager
│       │   ├── reconnect.py    # Auto-reconnect logic with backoff
│       │   └── health.py       # Connection health monitoring
│       ├── contracts/
│       │   ├── __init__.py
│       │   ├── resolver.py     # Option chain retrieval
│       │   └── cache.py        # Contract caching in Redis
│       ├── orders/
│       │   ├── __init__.py
│       │   ├── state_machine.py  # Order state machine
│       │   └── tracker.py      # Order state persistence
│       ├── db/
│       │   ├── __init__.py
│       │   ├── engine.py       # SQLAlchemy async engine setup
│       │   ├── models.py       # SQLAlchemy ORM models
│       │   └── session.py      # Session factory
│       ├── cache/
│       │   ├── __init__.py
│       │   └── redis.py        # Redis connection and helpers
│       └── kill_switch.py      # Emergency position close
├── tests/
│   ├── conftest.py
│   ├── test_connection.py
│   ├── test_contracts.py
│   ├── test_orders.py
│   └── test_state_machine.py
├── .env.example                # Template for local env vars
└── .gitignore
```

### Pattern 1: Layered Configuration with Pydantic Settings

**What:** Type-safe configuration loaded from YAML files with environment variable overrides and Docker secrets for sensitive values.
**When to use:** Every component needs configuration; this is the single source of truth.

```python
# src/trading/config.py
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class IBConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4002          # Paper trading port default
    client_id: int = 1
    timeout: float = 30.0
    max_reconnect_attempts: int = 0  # 0 = infinite
    reconnect_delay: float = 5.0
    reconnect_max_delay: float = 120.0

class TradingConfig(BaseModel):
    mode: str = "paper"        # "paper" or "live" -- defaults to paper (safety)

    @property
    def ib_port(self) -> int:
        """Return correct port based on trading mode."""
        return 4001 if self.mode == "live" else 4002

class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading"
    pool_size: int = 10
    pool_overflow: int = 5

class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379/0"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRADING_",
        env_nested_delimiter="__",
        yaml_file=["config/default.yml", "config/paper.yml"],
        secrets_dir="/run/secrets",
    )

    trading: TradingConfig = TradingConfig()
    ib: IBConfig = IBConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
```

**Paper/live toggle:** Change `TRADING_MODE=live` env var or update the YAML config file. The `TradingConfig.ib_port` property automatically selects port 4001 (live) or 4002 (paper). Default is always paper (safety).

### Pattern 2: IB Connection Manager with Auto-Reconnect

**What:** Singleton connection manager that handles initial connection, disconnection events, and exponential backoff reconnection.
**When to use:** All IB API interactions go through this manager.

```python
# src/trading/core/connection.py
import asyncio
import structlog
from ib_async import IB
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

logger = structlog.get_logger()

class IBConnectionManager:
    def __init__(self, config):
        self.config = config
        self.ib = IB()
        self._connected = asyncio.Event()
        self._shutdown = False

        # Attach disconnect handler ONCE (critical -- never in reconnect loop)
        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.connectedEvent += self._on_connected

    async def connect(self):
        """Initial connection with retry."""
        await self._do_connect()

    async def _do_connect(self):
        """Connect with exponential backoff."""
        attempt = 0
        while not self._shutdown:
            try:
                attempt += 1
                port = self.config.trading.ib_port
                await self.ib.connectAsync(
                    host=self.config.ib.host,
                    port=port,
                    clientId=self.config.ib.client_id,
                    timeout=self.config.ib.timeout,
                )
                logger.info("ib.connected", port=port, mode=self.config.trading.mode)
                self._connected.set()
                return
            except Exception as e:
                delay = min(
                    self.config.ib.reconnect_delay * (2 ** attempt),
                    self.config.ib.reconnect_max_delay
                )
                logger.warning("ib.connect_failed", attempt=attempt, error=str(e), retry_in=delay)
                await asyncio.sleep(delay)

    def _on_connected(self):
        self._connected.set()
        logger.info("ib.connected_event")

    def _on_disconnected(self):
        """Handle disconnection -- trigger reconnect."""
        self._connected.clear()
        if not self._shutdown:
            logger.warning("ib.disconnected", reconnecting=True)
            asyncio.ensure_future(self._do_connect())

    async def disconnect(self):
        """Graceful shutdown."""
        self._shutdown = True
        self.ib.disconnect()

    async def wait_connected(self):
        """Block until connected."""
        await self._connected.wait()
```

### Pattern 3: Order State Machine

**What:** Deterministic state machine tracking IB order lifecycle with database persistence.
**When to use:** Every order placed through the system.

```python
# src/trading/orders/state_machine.py
from statemachine import StateMachine, State

class OrderStateMachine(StateMachine):
    """Tracks IB order lifecycle.

    IB Order States:
      ApiPending -> PendingSubmit -> PreSubmitted -> Submitted -> Filled
                                                               -> Cancelled
                                                  -> PendingCancel -> Cancelled
                                                               -> ApiCancelled
                                  -> Inactive (error/rejection)
    """
    # States
    created = State(initial=True)
    api_pending = State()
    pending_submit = State()
    pre_submitted = State()
    submitted = State()
    pending_cancel = State()
    filled = State(final=True)
    cancelled = State(final=True)
    error = State(final=True)

    # Transitions
    submit = created.to(api_pending)
    sent = api_pending.to(pending_submit)

    accept = pending_submit.to(submitted) | pre_submitted.to(submitted)
    pre_submit = pending_submit.to(pre_submitted)

    request_cancel = (
        pending_submit.to(pending_cancel) |
        pre_submitted.to(pending_cancel) |
        submitted.to(pending_cancel)
    )

    fill = submitted.to(filled) | pre_submitted.to(filled)
    cancel = pending_cancel.to(cancelled) | submitted.to(cancelled)
    api_cancel = pending_cancel.to(cancelled) | api_pending.to(cancelled)

    reject = (
        api_pending.to(error) |
        pending_submit.to(error) |
        pre_submitted.to(error) |
        submitted.to(error)
    )

    def on_enter_state(self, source, target, event):
        """Called on every state transition -- persist to database."""
        # Log and persist transition
        pass
```

### Pattern 4: Docker Compose Service Orchestration

**What:** All infrastructure services in Docker Compose with proper health checks and networking.
**When to use:** Development and production deployment.

```yaml
# docker-compose.yml
services:
  ib-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:stable
    restart: unless-stopped
    environment:
      TWS_USERID: ${TWS_USERID}
      TWS_PASSWORD: ${TWS_PASSWORD}
      TRADING_MODE: ${TRADING_MODE:-paper}
      AUTO_RESTART_TIME: "11:55 PM ET"
      TWOFA_TIMEOUT_ACTION: restart
    ports:
      - "127.0.0.1:4001:4001"  # Live
      - "127.0.0.1:4002:4002"  # Paper
      - "127.0.0.1:5900:5900"  # VNC (dev only)
    volumes:
      - ib-gateway-data:/root

  timescaledb:
    image: timescale/timescaledb:latest-pg16
    restart: unless-stopped
    environment:
      POSTGRES_DB: trading
      POSTGRES_USER: trading
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-trading}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - timescaledb-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U trading"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  ib-gateway-data:
  timescaledb-data:
  redis-data:
```

### Anti-Patterns to Avoid

- **Attaching event handlers inside reconnect loops:** Each reconnection adds another handler, causing exponential callback duplication. Attach `disconnectedEvent` handler exactly ONCE at initialization.
- **Blocking the asyncio event loop:** Never use `time.sleep()` in async code. Use `asyncio.sleep()`. Never run synchronous IB API calls from async context.
- **Hardcoding ports for paper/live:** Use configuration-driven port selection. Port 4001 = live, 4002 = paper. One config value toggles everything.
- **Using `reqContractDetails` for option chains:** This is throttled and slow for large chains. Use `reqSecDefOptParams` which is specifically designed for option chain retrieval without throttling.
- **Storing IB credentials in config files:** Use environment variables or Docker secrets. Never commit credentials to git.
- **Creating the IB object per-request:** The `IB()` object manages a persistent TCP socket. Create one instance and reuse it across the application lifecycle.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| IB API binary protocol | Socket-level IB communication | `ib_async` | Handles message framing, async I/O, event dispatch, reconnection internally |
| Retry with backoff | Custom retry loops with sleep | `tenacity` | Handles jitter, exponential backoff, stop conditions, retry predicates |
| Configuration validation | Manual env var parsing with type coercion | `pydantic-settings` | Type validation, nested models, layered sources, secrets support |
| State machine | if/elif chains or dict-based transitions | `python-statemachine` | Enforces valid transitions, entry/exit callbacks, visualization, async support |
| Database migrations | Manual ALTER TABLE scripts | `alembic` | Version tracking, rollback, auto-generation from model changes |
| Structured logging | Print statements or basic `logging` | `structlog` | JSON output, context binding, processor pipeline, async-safe |
| Connection pooling (Redis) | Manual connection management | `redis.asyncio.ConnectionPool` | Built into `redis-py`; handles connection lifecycle, health checks |
| Connection pooling (PG) | Manual connection management | SQLAlchemy async engine pool | Built-in pool with configurable size, overflow, recycle |

**Key insight:** The IB API is notoriously difficult to work with directly. The `ib_async` library abstracts away the entire binary protocol, event-driven callback system, and socket management. Hand-rolling any of this is a multi-month effort that adds no value.

## Common Pitfalls

### Pitfall 1: IB Gateway Daily Restart Window
**What goes wrong:** IB Gateway restarts daily (configurable time, typically ~11:45 PM ET). During restart, the TCP socket closes. If your application doesn't handle this, it silently loses connection and stops receiving data/executing orders.
**Why it happens:** IB requires daily authentication refresh. The auto-restart feature in IB Gateway handles re-authentication but drops all API connections during the restart window (typically 1-3 minutes).
**How to avoid:** Use `disconnectedEvent` handler to trigger reconnection with exponential backoff. Set `AUTO_RESTART_TIME` in Docker config. Expect daily disconnections and design around them.
**Warning signs:** Orders placed late at night silently fail; morning data is stale; no error logs because the disconnect wasn't caught.

### Pitfall 2: Event Handler Duplication
**What goes wrong:** Reconnection logic that attaches a new `disconnectedEvent` handler each time creates exponentially growing callbacks. After N reconnections, one disconnect triggers N handlers, each trying to reconnect simultaneously.
**Why it happens:** The reconnect function registers a new handler before reconnecting. Natural pattern but devastating with event-driven APIs.
**How to avoid:** Attach all IB event handlers exactly ONCE during initialization. Never attach handlers inside reconnection logic.
**Warning signs:** Log messages multiply with each reconnection; multiple simultaneous connection attempts.

### Pitfall 3: Paper/Live Port Confusion
**What goes wrong:** System connects to live trading when developer intended paper, or vice versa. IB Gateway uses port 4001 for live and 4002 for paper -- swapping them has immediate financial consequences.
**Why it happens:** Port numbers are "just numbers" in config; easy to misconfigure. Some Docker images have different default port mappings.
**How to avoid:** Derive port from `trading_mode` configuration, never set port directly. Default to paper mode. Add startup banner that clearly shows which mode is active. Log `TRADING MODE: PAPER` or `TRADING MODE: LIVE` prominently on every startup.
**Warning signs:** Test orders executing on live account; unexpected fills showing in brokerage.

### Pitfall 4: IB Client ID Conflicts
**What goes wrong:** If two application instances connect with the same `clientId`, the second connection kicks out the first. This causes silent disconnection of the primary instance.
**Why it happens:** IB Gateway allows only one connection per `clientId`. Default `clientId=0` in many examples.
**How to avoid:** Use a configurable, unique `clientId` per instance. Never use `clientId=0` (reserved for TWS manual use). Use different IDs for different application components if multiple connections are needed.
**Warning signs:** Intermittent disconnections; "already connected" errors; ghost orders.

### Pitfall 5: TimescaleDB Hypertable Timing
**What goes wrong:** Attempting to create a hypertable on a table that already has data, or creating it before inserting the time column, causes errors.
**Why it happens:** `create_hypertable()` must be called on an empty table. Alembic migrations run in order, so the hypertable creation must be in the same migration as table creation, before any data insertion.
**How to avoid:** In Alembic migration: CREATE TABLE first, then immediately `SELECT create_hypertable(...)` in the same migration step. Never add hypertable conversion as a separate, later migration.
**Warning signs:** Migration errors about "table already contains data"; hypertable not created.

### Pitfall 6: Async Alembic Configuration
**What goes wrong:** Alembic migrations fail with "cannot use async engine" or block the event loop.
**Why it happens:** Default Alembic `env.py` uses synchronous database drivers. When your application uses `asyncpg`, you need the async Alembic template.
**How to avoid:** Initialize Alembic with `alembic init --template async alembic/`. Use `async_engine_from_config` in `env.py`. Wrap synchronous migration operations with `connection.run_sync()`.
**Warning signs:** Migrations hang; "event loop already running" errors; `asyncpg` not found errors.

### Pitfall 7: IB Gateway 2FA in Docker
**What goes wrong:** Container starts but never establishes connection because it's waiting for two-factor authentication that nobody completes.
**Why it happens:** IB requires 2FA authentication. Docker containers can't display 2FA prompts. Weekly Sunday re-authentication at 1:00 AM ET requires manual intervention.
**How to avoid:** Configure `AUTO_RESTART_TIME` (not `AUTO_LOGOFF_TIME`). Set `TWOFA_TIMEOUT_ACTION=restart`. Set `RELOGIN_AFTER_TWOFA_TIMEOUT=yes` for automatic retry. Accept that Sunday re-auth needs a manual 2FA approval (via mobile app).
**Warning signs:** Container running but API port not responding; VNC shows login screen.

## Code Examples

### Option Chain Retrieval (from ib_insync official notebook, API identical in ib_async)
```python
# Source: https://github.com/erdewit/ib_insync/blob/master/notebooks/option_chain.ipynb
from ib_async import IB, Stock, Index, Option

async def get_option_chain(ib: IB, symbol: str, sec_type: str = "STK"):
    """Retrieve full option chain for an underlying."""
    # 1. Create and qualify the underlying contract
    if sec_type == "STK":
        underlying = Stock(symbol, "SMART", "USD")
    elif sec_type == "IND":
        underlying = Index(symbol, "CBOE", "USD")
    # For futures: Future(symbol, exchange=..., lastTradeDateOrContractMonth=...)

    await ib.qualifyContractsAsync(underlying)

    # 2. Get option chain parameters (not throttled, unlike reqContractDetails)
    chains = await ib.reqSecDefOptParamsAsync(
        underlying.symbol, "", underlying.secType, underlying.conId
    )

    # 3. Filter to desired exchange/trading class
    chain = next(
        c for c in chains
        if c.exchange == "SMART" and c.tradingClass == symbol
    )

    # 4. chain.strikes = frozenset of all available strikes
    #    chain.expirations = frozenset of all available expirations (YYYYMMDD)
    return chain

async def qualify_options(ib: IB, symbol: str, expirations: list,
                          strikes: list, rights: list = ["C", "P"]):
    """Build and qualify specific option contracts."""
    contracts = [
        Option(symbol, exp, strike, right, "SMART", tradingClass=symbol)
        for right in rights
        for exp in expirations
        for strike in strikes
    ]
    qualified = await ib.qualifyContractsAsync(*contracts)
    # Returns list with None for any contracts that couldn't be qualified
    return [c for c in qualified if c is not None]
```

### Redis Contract Cache Pattern
```python
# Source: redis-py official async patterns
import json
from redis.asyncio import Redis

class ContractCache:
    """Cache qualified contracts and option chains in Redis."""

    def __init__(self, redis: Redis, ttl: int = 3600):
        self.redis = redis
        self.ttl = ttl

    async def get_chain(self, symbol: str) -> dict | None:
        data = await self.redis.get(f"chain:{symbol}")
        return json.loads(data) if data else None

    async def set_chain(self, symbol: str, chain_data: dict):
        await self.redis.set(
            f"chain:{symbol}",
            json.dumps(chain_data),
            ex=self.ttl,
        )

    async def invalidate_chain(self, symbol: str):
        await self.redis.delete(f"chain:{symbol}")
```

### Async SQLAlchemy Engine Setup
```python
# Source: SQLAlchemy 2.0 async documentation
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

def create_engine(database_url: str, pool_size: int = 10):
    engine = create_async_engine(
        database_url,
        pool_size=pool_size,
        pool_pre_ping=True,  # Verify connections before use
        echo=False,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
```

### TimescaleDB Model with Hypertable
```python
# Source: sqlalchemy-timescaledb + TimescaleDB docs
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum
from sqlalchemy.orm import DeclarativeBase
import enum

class Base(DeclarativeBase):
    pass

class OrderState(str, enum.Enum):
    CREATED = "created"
    API_PENDING = "api_pending"
    PENDING_SUBMIT = "pending_submit"
    PRE_SUBMITTED = "pre_submitted"
    SUBMITTED = "submitted"
    PENDING_CANCEL = "pending_cancel"
    FILLED = "filled"
    CANCELLED = "cancelled"
    ERROR = "error"

class OrderStateTransition(Base):
    """Tracks every order state change as a time-series event."""
    __tablename__ = "order_state_transitions"
    __table_args__ = {
        "timescaledb_hypertable": {
            "time_column_name": "timestamp",
        }
    }

    timestamp = Column(DateTime(timezone=True), primary_key=True)
    order_id = Column(String, primary_key=True)
    from_state = Column(Enum(OrderState))
    to_state = Column(Enum(OrderState), nullable=False)
    ib_order_id = Column(Integer)
    details = Column(String)  # JSON string with additional context
```

### Kill Switch Pattern
```python
# Source: IB TWS API reqGlobalCancel + position close pattern
import structlog

logger = structlog.get_logger()

class KillSwitch:
    """Emergency: cancel all orders and optionally close all positions."""

    def __init__(self, ib: IB):
        self.ib = ib

    async def cancel_all_orders(self):
        """Cancel every open order via IB global cancel."""
        self.ib.reqGlobalCancel()
        logger.critical("kill_switch.all_orders_cancelled")

    async def close_all_positions(self):
        """Cancel orders then close all positions with market orders."""
        await self.cancel_all_orders()

        positions = self.ib.positions()
        for pos in positions:
            if pos.position != 0:
                # Create closing order (opposite direction)
                from ib_async import MarketOrder
                action = "SELL" if pos.position > 0 else "BUY"
                close_order = MarketOrder(action, abs(pos.position))
                trade = self.ib.placeOrder(pos.contract, close_order)
                logger.critical(
                    "kill_switch.closing_position",
                    symbol=pos.contract.symbol,
                    position=pos.position,
                    order_id=trade.order.orderId,
                )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ib_insync` | `ib_async` (ib-api-reloaded) | 2024 (original author passed away) | Must use `ib_async` for maintained library; API is nearly identical |
| `aioredis` separate package | `redis[hiredis]` with `redis.asyncio` | 2023 (aioredis merged) | Single `redis-py` package for both sync and async |
| SQLAlchemy 1.x with sync drivers | SQLAlchemy 2.0 + asyncpg | 2023 | Native async ORM; 2.0-style queries with `select()` |
| `python-dotenv` only config | `pydantic-settings` with layered sources | 2023+ | Type-safe, validated config from multiple sources |
| Manual env var parsing | `pydantic-settings` YAML + env + secrets | 2024+ | `YamlConfigSettingsSource` added to pydantic-settings |

**Deprecated/outdated:**
- `ib_insync`: Use `ib_async` instead. Same API, active maintenance.
- `aioredis`: Merged into `redis-py`. Import from `redis.asyncio` instead.
- `psycopg2` for async: Use `asyncpg` with SQLAlchemy async.
- Alembic sync template with async engines: Use `alembic init --template async`.

## Open Questions

1. **IB Gateway Docker Image Stability**
   - What we know: `gnzsnz/ib-gateway` is the most actively maintained community image with regular updates tracking IB Gateway releases. Current stable tag is `10.37.1p`.
   - What's unclear: Long-term reliability in production 24/7 operation. Community reports are mostly positive but no formal SLA.
   - Recommendation: Use the `stable` tag (not `latest`), pin to a specific version in production, test fail-over during development.

2. **2FA Weekly Re-authentication**
   - What we know: IB requires re-authentication every Sunday at 1:00 AM ET. Docker container cannot handle 2FA automatically.
   - What's unclear: Whether IBKR Key authentication (hardware token) can be automated, or if mobile app approval is always required.
   - Recommendation: Accept manual Sunday re-auth for now. Set `TWOFA_TIMEOUT_ACTION=restart` so the container retries after user approves via mobile. Monitor for IBKR API changes that might improve this.

3. **TimescaleDB Compression and Retention**
   - What we know: TimescaleDB supports automatic compression and retention policies on hypertables.
   - What's unclear: Optimal chunk interval and compression age for options trading data (tick data vs order data have very different characteristics).
   - Recommendation: Start with 1-day chunks for tick data, 1-week chunks for order data. Enable compression after 7 days. Set retention to 1 year initially. Tune based on actual data volumes.

4. **py_vollib Python 3.12+ Compatibility**
   - What we know: py_vollib last released in 2017. Flagged as a concern in STATE.md.
   - What's unclear: Whether it works on Python 3.12/3.13.
   - Recommendation: This is a Phase 2 (Market Data & Analytics) concern, not Phase 1. Defer to Phase 2 research. Phase 1 has no volatility calculation needs.

## Sources

### Primary (HIGH confidence)
- [ib_async GitHub](https://github.com/ib-api-reloaded/ib_async) - Version 2.1.0, API documentation, changelog
- [ib_async API docs](https://ib-api-reloaded.github.io/ib_async/api.html) - Connection, order, contract APIs
- [ib_async changelog](https://ib-api-reloaded.github.io/ib_async/changelog.html) - v2.1.0 released 2025-12-06
- [gnzsnz/ib-gateway-docker GitHub](https://github.com/gnzsnz/ib-gateway-docker) - Docker image configuration, trading modes
- [IB TWS API Options docs](https://interactivebrokers.github.io/tws-api/options.html) - reqSecDefOptParams
- [IB TWS API Order Submission](https://interactivebrokers.github.io/tws-api/order_submission.html) - Order status states
- [Pydantic Settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) - Configuration sources, YAML, secrets
- [SQLAlchemy 2.0 AsyncIO docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) - Async engine, session patterns
- [ib_insync option chain notebook](https://github.com/erdewit/ib_insync/blob/master/notebooks/option_chain.ipynb) - reqSecDefOptParams usage pattern

### Secondary (MEDIUM confidence)
- [gnzsnz/ib-gateway Docker Hub](https://hub.docker.com/r/gnzsnz/ib-gateway) - Image tags, configuration
- [pytransitions/transitions GitHub](https://github.com/pytransitions/transitions) - v0.9.4 state machine library
- [python-statemachine PyPI](https://pypi.org/project/python-statemachine/) - v3.0, declarative API, async support
- [sqlalchemy-timescaledb GitHub](https://github.com/dorosch/sqlalchemy-timescaledb) - TimescaleDB dialect for SQLAlchemy
- [IBKR auto-restart considerations](https://www.ibkrguides.com/traderworkstation/auto-restart-considerations.htm) - Daily restart behavior
- [ib_insync reconnection issue #41](https://github.com/erdewit/ib_insync/issues/41) - Reconnection patterns and anti-patterns

### Tertiary (LOW confidence)
- [uv monorepo best practices](https://github.com/astral-sh/uv/issues/10960) - Community-documented, not official
- [TimescaleDB tick data tutorial](https://docs.timescale.com/tutorials/latest/financial-tick-data/financial-tick-dataset/) - General pattern, not options-specific

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified via official documentation and GitHub repos with current version numbers
- Architecture: HIGH - Patterns derived from official examples (ib_insync notebooks, SQLAlchemy async docs, pydantic-settings docs)
- IB Connection/Reconnect: HIGH - Verified via ib_async docs, IB TWS API docs, and community issue discussions
- Docker/Infrastructure: MEDIUM - gnzsnz/ib-gateway is community-maintained; configuration verified but long-term production stability is unproven
- Order State Machine: HIGH - IB order states verified via official TWS API docs; state machine library verified
- Pitfalls: HIGH - Most pitfalls sourced from official docs or well-documented community issues

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (30 days - stack is mature and stable)
