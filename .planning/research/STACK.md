# Technology Stack

**Project:** AI-Powered Multi-Agent Options Trading System
**Researched:** 2026-03-25
**Overall Confidence:** HIGH (all versions verified via PyPI/npm, rationale cross-referenced)

---

## Design Principles

Before listing technologies, the guiding principles that drove every choice:

1. **Python-first backend** -- The IB API ecosystem, quant libraries, and AI/ML tooling all center on Python. Fighting this means fighting the ecosystem.
2. **Async-native** -- Trading systems are I/O bound (market data streams, API calls, LLM inference). Asyncio is not optional; it is the architectural foundation.
3. **Separation of concerns** -- The agent orchestration layer, the execution layer, and the dashboard are distinct services communicating via well-defined interfaces.
4. **Paper-first** -- Every component must work identically in paper and live mode. This is a deployment toggle, not a code branch.
5. **Minimal framework lock-in** -- Prefer composable libraries over monolithic frameworks. You should be able to swap the LLM provider, the charting library, or the database without rewriting the system.

---

## Recommended Stack

### Language & Runtime

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **Python** | 3.12+ | Primary language | HIGH | Required by ib_async (3.10+), FastAPI, LangGraph. 3.12 offers TaskGroup improvements for asyncio and faster CPython. Avoid 3.14 (too bleeding edge). |
| **Node.js** | 22 LTS | Frontend toolchain | HIGH | Required for Next.js 16. LTS release ensures stability. |

### Interactive Brokers Connectivity

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **ib_async** | 2.1.0 | IB TWS/Gateway API client | HIGH | The actively maintained successor to ib_insync (original author passed away in early 2024). Implements the IBKR binary protocol internally -- no separate `ibapi` package needed. Pure asyncio, Jupyter-friendly, production-ready with automatic reconnection. Maintained by Matt Stancliff under `ib-api-reloaded` org. |
| **IB Gateway** | Latest (10.42+) | Headless IB connection | HIGH | Use Gateway instead of TWS for production. Headless, lighter, more stable for 24/7 operation. TWS is for development/debugging only. |

**Do NOT use:**
- `ib_insync` -- Unmaintained since creator's death. ib_async is the direct continuation.
- `ibapi` (official IB Python API) -- Callback-based, low-level, painful to work with. ib_async wraps the binary protocol directly and is far more ergonomic.
- Third-party REST wrappers (e.g., `ib-web-api`) -- Adds latency, another failure point, and limited feature coverage.

### AI / LLM Integration

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **anthropic** (SDK) | 0.86.0 | Primary LLM provider | HIGH | Claude for complex reasoning tasks (strategy generation, risk analysis, market interpretation). Superior at structured output and tool use. |
| **openai** (SDK) | 2.29.0 | Secondary LLM provider | HIGH | GPT-4o/GPT-4o-mini for faster, cheaper tasks (scanning, classification, summarization). Having two providers avoids single-vendor lock-in and lets you route by cost/latency/quality. |
| **PydanticAI** | 1.71.0 | Agent framework (per-agent) | HIGH | Lightweight, production-stable (v1.71), Pydantic-native. Each trading agent (scanner, strategist, risk manager, executor) is a PydanticAI agent with typed inputs/outputs and tool definitions. Minimal overhead vs. raw SDK calls. Model-agnostic -- supports Claude, GPT, Gemini, local models. |
| **LangGraph** | 1.1.3 | Agent orchestration (workflow) | HIGH | Orchestrates the multi-agent pipeline as a state machine: scanner -> strategist -> risk manager -> executor. Provides human-in-the-loop interrupts (critical for trade approval), state persistence, retry logic, and time-travel debugging. LangGraph 1.0 shipped Oct 2025 -- first stable major release. |

**Architecture decision -- PydanticAI + LangGraph (not either/or):**

This is the critical stack decision. Use them at different layers:

- **PydanticAI** defines each individual agent (scanner agent, strategist agent, etc.) with typed tool calls, structured outputs, and model routing. It is the "agent SDK."
- **LangGraph** orchestrates the flow between agents as a directed graph with state. It is the "workflow engine."

This avoids LangGraph's overhead at the per-agent level (where PydanticAI is lighter) while gaining LangGraph's state machine benefits at the orchestration level (where you need persistence, human-in-the-loop, and error recovery).

**Do NOT use:**
- `CrewAI` -- Higher-level abstraction that hides control flow. For a trading system where you need deterministic execution order (bull case before bear case, risk check before execution), LangGraph's explicit graph is superior. CrewAI is better for open-ended collaborative AI tasks, not for safety-critical financial workflows.
- Raw LangChain agents -- Deprecated pattern. LangGraph is LangChain's recommended successor for agent workflows.
- `AutoGen` (Microsoft) -- Research-oriented, less production-proven. Architecture emphasizes multi-agent chat, which maps poorly to a sequential trading pipeline.
- Custom from scratch -- Tempting for latency, but you lose human-in-the-loop, state persistence, and retry/recovery. Build custom only if LangGraph proves too slow (measure first).

### Options Analytics & Quantitative Libraries

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **py_vollib** | 1.0.1 | Options pricing & Greeks (analytical) | MEDIUM | Black-Scholes, Black, BSM pricing. Built on Peter Jackel's LetsBeRational for fast implied volatility. Version is old (2017) but mathematically stable -- options math doesn't change. |
| **py_vollib_vectorized** | 0.1.1 | Vectorized Greeks for bulk calculations | MEDIUM | Wraps py_vollib with numpy/pandas vectorization + numba JIT. Fastest Python library for batch pricing thousands of contracts. Essential for screening options chains. Version from 2021 but numba-accelerated math is timeless. |
| **numpy** | Latest (2.x) | Numerical computing | HIGH | Foundation for all quant calculations. |
| **pandas** | Latest (2.x) | Time series data manipulation | HIGH | Industry standard for OHLCV, options chains, portfolio data. |
| **polars** | Latest (1.x) | High-performance DataFrames | HIGH | 10-50x faster than pandas for large datasets. Use for historical backtesting and bulk data processing. Keep pandas for IB API integration (ib_async returns pandas). |
| **scipy** | Latest | Statistical functions | HIGH | Distribution functions, optimization, statistical tests for strategy validation. |

**Do NOT use:**
- `QuantLib-Python` -- Massively over-engineered for this use case. QuantLib is a derivatives pricing library for exotic instruments and yield curves. For listed equity/ETF/futures options with standard Greeks, py_vollib is simpler, faster, and sufficient. Bring QuantLib in later only if you need exotic pricing.
- Custom Greeks implementation -- Tempting but error-prone. Use battle-tested libraries.

### Web Backend (API + WebSocket Server)

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **FastAPI** | 0.135.2 | REST API + WebSocket server | HIGH | Async-native, Pydantic-integrated, auto-generated OpenAPI docs. The standard Python API framework in 2025-2026. Native WebSocket support for real-time dashboard updates. |
| **uvicorn** | 0.42.0 | ASGI server | HIGH | Lightning-fast ASGI server. Production deployment with `--workers` for multi-process. |
| **Pydantic** | 2.x (latest) | Data validation & serialization | HIGH | Already required by FastAPI and PydanticAI. Use everywhere for type-safe data contracts between agents, API, and database. |
| **pydantic-settings** | 2.13.1 | Configuration management | HIGH | Type-safe settings from env vars, .env files, TOML. Critical for managing IB credentials, API keys, trading parameters, risk limits. Supports SecretStr for sensitive values. |

**Do NOT use:**
- `Flask` -- Synchronous, no native async. Fundamentally wrong for a system built on asyncio.
- `Django` -- Too heavyweight. ORM assumptions conflict with time-series database needs. Admin panel is not useful for trading dashboards.
- `Streamlit` -- Great for prototyping, terrible for production dashboards. No WebSocket control, no custom styling, single-threaded.

### Web Frontend (Dashboard)

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **Next.js** | 16.x (16.2.1) | React meta-framework | HIGH | App Router, Turbopack (stable in v16), React Compiler (auto-memoization). Server components for initial load, client components for real-time updates. |
| **React** | 19.x | UI library | HIGH | Bundled with Next.js 16. |
| **lightweight-charts** | Latest (4.x) | TradingView-style charts | HIGH | Apache 2.0 licensed. Smallest and fastest financial HTML5 charts. Built by TradingView. Native React integration via wrapper. Renders candlestick, line, area, histogram charts. Plugin system for custom indicators. |
| **Tailwind CSS** | 4.x | Styling | HIGH | Utility-first CSS. Fast iteration on dashboard layouts. |
| **Zustand** | Latest | Client state management | MEDIUM | Lightweight alternative to Redux. Perfect for WebSocket state, trading blotter, position tracking. Minimal boilerplate. |
| **TanStack Query** | Latest (v5) | Server state / API calls | MEDIUM | For REST API data fetching, caching, and refetching. Pairs with WebSocket for hybrid data strategy: REST for initial load, WebSocket for live updates. |

**Do NOT use:**
- `Recharts` / `Chart.js` -- Not designed for financial data. No candlestick support, no crosshair, no price scales.
- `TradingView Advanced Charts` (full widget) -- Requires commercial license for production. Lightweight-charts is the free, open-source alternative from the same team.
- `Redux` -- Over-engineered for this use case. Zustand provides the same functionality with 90% less boilerplate.

### Database

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **PostgreSQL** | 16+ | Relational data (accounts, strategies, configurations, trade records, audit log) | HIGH | Battle-tested, full ACID, JSON support for flexible schemas. The relational backbone. |
| **TimescaleDB** | Latest (2.x extension) | Time-series data (OHLCV bars, Greeks snapshots, P&L time series) | HIGH | PostgreSQL extension -- same connection, same SQL, same tooling. Hypertables provide automatic time-based partitioning. Continuous aggregates for pre-computed rollups. Avoids running a separate database. |
| **Redis** | 7.4.0 | Cache, pub/sub, real-time state | HIGH | In-memory data store for: (1) real-time position/Greeks cache, (2) pub/sub between trading engine and dashboard, (3) rate limiting, (4) session state. Redis Streams for durable event log if needed. |

**Architecture decision -- PostgreSQL + TimescaleDB (not a separate TSDB):**

QuestDB is 6-13x faster than TimescaleDB for raw ingestion and analytical queries. However, for this system:
- You are NOT doing HFT. Options trading operates on seconds-to-minutes timescales, not microseconds.
- TimescaleDB runs inside PostgreSQL. One database to manage, one connection pool, one backup strategy, one migration tool.
- SQLAlchemy + Alembic work seamlessly with TimescaleDB. QuestDB has no SQLAlchemy integration.
- The operational simplicity of a single database massively outweighs the performance gap at this scale.

Revisit QuestDB only if you are storing tick-level data for 5000+ symbols simultaneously and query performance becomes a bottleneck. For options trading on US equities/ETFs/futures, TimescaleDB is more than sufficient.

**Do NOT use:**
- `QuestDB` or `InfluxDB` as primary -- Running a separate time-series database adds operational complexity (two backup strategies, two migration tools, two connection pools) with no benefit at this scale.
- `MongoDB` -- Document databases are a poor fit for time-series financial data and relational trade records.
- `SQLite` -- No concurrent writes, no time-series optimization, no pub/sub.

### ORM & Migrations

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **SQLAlchemy** | 2.0.48 | ORM + raw SQL | HIGH | The Python ORM. v2.0 has modern async support via `asyncpg`. Use declarative models for relational data, raw SQL for time-series queries where ORM overhead is unwanted. |
| **Alembic** | 1.18.4 | Database migrations | HIGH | From the SQLAlchemy author. Auto-generates migrations from model changes. DAG-based version tracking. Essential for managing schema evolution as the trading system grows. |
| **asyncpg** | Latest | Async PostgreSQL driver | HIGH | Fastest async PostgreSQL driver for Python. Used by SQLAlchemy's async engine. |

### Message Passing & Event Bus

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **Redis Pub/Sub** | (via redis 7.4.0) | Real-time inter-service messaging | HIGH | Already using Redis for caching. Pub/sub for: market data events -> agents, trade signals -> executor, position updates -> dashboard. Zero additional infrastructure. |
| **Redis Streams** | (via redis 7.4.0) | Durable event log | HIGH | When you need message persistence (audit trail, replay). Consumer groups for load distribution. Better than Kafka for this scale. |
| **asyncio queues** | (stdlib) | In-process event routing | HIGH | For communication between components within the same process. Zero overhead, zero infrastructure. |

**Do NOT use:**
- `Kafka` -- Massively over-engineered for a single-user trading system. Kafka is for millions of events/sec across distributed systems. Redis Streams provides the same durability guarantees at this scale.
- `RabbitMQ` -- Adds infrastructure complexity. Redis already provides pub/sub and streams. Don't run two message brokers.
- `ZeroMQ` -- Brokerless is elegant but requires each component to know about all others. Redis provides central pub/sub with zero discovery complexity.
- `Celery` -- Heavy, complex, requires a broker anyway. For this system, asyncio task scheduling + Redis is simpler and faster.

### Task Scheduling

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **APScheduler** | 4.x | Scheduled tasks (market open/close, daily reports, Greeks recalculation) | MEDIUM | AsyncIOScheduler integrates with the asyncio event loop. Lightweight, no external broker needed. Cron-like scheduling for recurring tasks. |
| **asyncio** | (stdlib) | Real-time task management | HIGH | `asyncio.create_task()`, `TaskGroup`, and event loops for all real-time processing. The foundation. |

**Do NOT use:**
- `Celery Beat` -- Requires a full Celery deployment with broker and worker processes. APScheduler runs in-process with the asyncio loop.

### Logging & Observability

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **structlog** | 25.5.0 | Structured logging | HIGH | JSON-structured logs with bound context (trade_id, agent_name, symbol). Integrates with OpenTelemetry, Datadog, ELK. Async-friendly. Essential for debugging multi-agent workflows -- you need to trace a decision through scanner -> strategist -> risk manager -> executor. |
| **prometheus_client** | Latest | Metrics export | MEDIUM | Expose metrics (order latency, agent inference time, P&L) for Prometheus/Grafana dashboards. |

**Do NOT use:**
- `loguru` -- Simpler API but worse structured logging support. structlog's context binding is critical for multi-agent traceability.
- `print()` -- Obviously. But worth stating: never use print for trading system logging.

### Testing

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **pytest** | Latest (8.x) | Test framework | HIGH | The Python testing standard. |
| **pytest-asyncio** | 1.3.0 | Async test support | HIGH | Test async functions, fixtures, and event loops. Essential for testing ib_async interactions. |
| **pytest-mock** | Latest | Mocking | HIGH | Mock IB API responses, LLM calls, market data. Critical for testing without live connections. |
| **httpx** | Latest | Async HTTP test client | HIGH | FastAPI's recommended test client. Async-native. |
| **factory_boy** | Latest | Test data factories | MEDIUM | Generate realistic trade records, positions, options chains for testing. |

### DevOps & Infrastructure

| Technology | Version | Purpose | Confidence | Why |
|------------|---------|---------|------------|-----|
| **Docker** | Latest | Containerization | HIGH | Each service (trading engine, API server, dashboard) runs in its own container. |
| **Docker Compose** | Latest | Local development orchestration | HIGH | One command to start: PostgreSQL + TimescaleDB, Redis, trading engine, API server, dashboard. Compose Watch for hot-reload during development. |
| **uv** | Latest | Python package management | HIGH | 10-100x faster than pip. Replaces pip, pip-tools, and virtualenv. Lock files for reproducible builds. The new standard for Python package management in 2025-2026. |
| **Ruff** | Latest | Linting + formatting | HIGH | Replaces flake8, black, isort in a single Rust-powered tool. 10-100x faster. |

**Do NOT use:**
- `pip` + `requirements.txt` -- Slow, no lock file, poor dependency resolution. uv is strictly superior.
- `poetry` -- Slower than uv, more complex. uv has won the Python packaging war.
- `conda` -- For data science environments, not production deployments.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| IB Client | ib_async 2.1.0 | ib_insync | Unmaintained since 2024. ib_async is the direct successor. |
| IB Client | ib_async 2.1.0 | Official ibapi | Callback-based, low-level, painful async story. |
| Agent Framework | PydanticAI | Raw SDK calls | Lose typed outputs, tool management, model-agnostic routing. |
| Orchestration | LangGraph | CrewAI | Need deterministic flow control for financial safety, not open-ended collaboration. |
| Orchestration | LangGraph | Custom state machine | Lose human-in-the-loop, persistence, retry, debugging. Build custom only if measured latency is unacceptable. |
| Options Math | py_vollib + vectorized | QuantLib | QuantLib is for exotic derivatives. Overkill for listed options. |
| Time-Series DB | TimescaleDB (PG ext.) | QuestDB standalone | Operational complexity of two databases not justified at this scale. |
| Message Broker | Redis Streams | Kafka | Kafka is for millions of events/sec across distributed systems. Way too heavy. |
| Task Scheduler | APScheduler | Celery | Celery requires full broker + worker infrastructure. APScheduler runs in-process. |
| Dashboard | Next.js + lightweight-charts | Streamlit | Streamlit is for prototyping, not production dashboards. No WebSocket control. |
| Logging | structlog | loguru | structlog's context binding is critical for multi-agent traceability. |
| Package Mgmt | uv | poetry | uv is 10-100x faster with better dependency resolution. |

---

## Full Dependency List

### Python Backend (trading engine + API)

```bash
# Core - IB connectivity
uv add ib_async                         # IB TWS/Gateway client (v2.1.0)

# Core - AI/LLM
uv add anthropic                        # Claude SDK (v0.86.0)
uv add openai                           # OpenAI SDK (v2.29.0)
uv add pydantic-ai                      # Agent framework (v1.71.0)
uv add langgraph                        # Agent orchestration (v1.1.3)

# Core - Web API
uv add fastapi                          # API framework (v0.135.2)
uv add uvicorn[standard]                # ASGI server (v0.42.0)
uv add pydantic-settings                # Config management (v2.13.1)
uv add websockets                       # WebSocket support

# Core - Database
uv add sqlalchemy[asyncio]              # ORM (v2.0.48)
uv add asyncpg                          # Async PostgreSQL driver
uv add alembic                          # Migrations (v1.18.4)
uv add redis                            # Redis client (v7.4.0)

# Core - Quantitative
uv add numpy pandas scipy               # Numerical computing
uv add polars                           # High-performance DataFrames
uv add py_vollib                        # Options pricing (v1.0.1)
uv add py_vollib_vectorized             # Vectorized Greeks (v0.1.1)

# Core - Scheduling & Logging
uv add apscheduler                      # Task scheduling (v4.x)
uv add structlog                        # Structured logging (v25.5.0)

# Dev dependencies
uv add --dev pytest pytest-asyncio pytest-mock pytest-cov
uv add --dev httpx                      # Async test client
uv add --dev factory-boy                # Test data factories
uv add --dev ruff                       # Linting + formatting
uv add --dev mypy                       # Type checking
```

### Frontend (Next.js dashboard)

```bash
# Core
npx create-next-app@latest dashboard --typescript --tailwind --app
cd dashboard

# Charting
npm install lightweight-charts

# State management
npm install zustand
npm install @tanstack/react-query

# UI Components (pick one)
npm install @radix-ui/react-dialog @radix-ui/react-dropdown-menu  # Headless UI
npm install class-variance-authority clsx tailwind-merge            # Style utilities

# WebSocket
npm install socket.io-client            # Or native WebSocket API
```

### Infrastructure (docker-compose.yml services)

```yaml
services:
  postgres:
    image: timescale/timescaledb:latest-pg16  # PostgreSQL 16 + TimescaleDB
    ports: ["5432:5432"]

  redis:
    image: redis:7.4-alpine
    ports: ["6379:6379"]

  trading-engine:
    build: ./engine
    depends_on: [postgres, redis]
    env_file: .env

  api-server:
    build: ./api
    depends_on: [postgres, redis]
    ports: ["8000:8000"]

  dashboard:
    build: ./dashboard
    depends_on: [api-server]
    ports: ["3000:3000"]

  ib-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:latest  # Community Docker image
    ports: ["4001:4001", "4002:4002"]
```

---

## Version Verification Sources

All versions verified via PyPI/npm on 2026-03-25:

| Package | Version | Source | Verified |
|---------|---------|--------|----------|
| ib_async | 2.1.0 | PyPI (released 2025-12-08) | YES |
| anthropic | 0.86.0 | PyPI (released 2026-03-18) | YES |
| openai | 2.29.0 | PyPI (released 2026-03-17) | YES |
| pydantic-ai | 1.71.0 | PyPI (released 2026-03-24) | YES |
| langgraph | 1.1.3 | PyPI (released 2026-03-18) | YES |
| fastapi | 0.135.2 | PyPI (released 2026-03-23) | YES |
| uvicorn | 0.42.0 | PyPI (released 2026-03-16) | YES |
| pydantic-settings | 2.13.1 | PyPI (released 2026-02-19) | YES |
| sqlalchemy | 2.0.48 | PyPI (released 2026-03-02) | YES |
| alembic | 1.18.4 | PyPI (released 2026-02-10) | YES |
| redis | 7.4.0 | PyPI (released 2026-03-24) | YES |
| structlog | 25.5.0 | PyPI (released 2025-10-27) | YES |
| pytest-asyncio | 1.3.0 | PyPI (released 2025-11-10) | YES |
| py_vollib | 1.0.1 | PyPI (released 2017-04-10) | YES |
| py_vollib_vectorized | 0.1.1 | PyPI (released 2021-02-28) | YES |
| Next.js | 16.2.1 | npm (current stable) | YES |

---

## Confidence Assessment

| Area | Confidence | Rationale |
|------|------------|-----------|
| IB Connectivity (ib_async) | HIGH | Verified on PyPI, GitHub, multiple community sources. Clear successor to ib_insync. |
| AI/LLM SDKs (anthropic, openai) | HIGH | Verified on PyPI. Standard, well-documented libraries. |
| Agent Framework (PydanticAI) | HIGH | Verified on PyPI at v1.71. Production-stable classification. Pydantic team maintains it. |
| Orchestration (LangGraph) | HIGH | Verified on PyPI at v1.1.3. Production-stable since v1.0 (Oct 2025). Multiple production case studies. |
| Options Analytics (py_vollib) | MEDIUM | Library works and math is correct, but last PyPI release was 2017 (py_vollib) and 2021 (vectorized). No maintenance risk for math, but potential Python compatibility issues with newer versions need testing. |
| Database (PostgreSQL + TimescaleDB) | HIGH | Industry standard. Well-documented. SQLAlchemy integration verified. |
| Web Stack (FastAPI + Next.js) | HIGH | Both verified at current versions. Standard pairing for Python API + React dashboard. |
| Message Passing (Redis) | HIGH | Verified on PyPI. Standard choice for cache + pub/sub + streams at this scale. |
| PydanticAI + LangGraph combo | MEDIUM | Both libraries verified individually. The two-layer pattern (PydanticAI per-agent, LangGraph for orchestration) is architecturally sound but not commonly documented as a specific pattern. May need custom integration work. |

---

## Open Questions for Phase-Specific Research

1. **IB Gateway Docker image stability** -- The community image `ghcr.io/gnzsnz/ib-gateway` needs validation. Official IB does not provide Docker images. This is a potential fragility point.

2. **py_vollib Python 3.12+ compatibility** -- Last release in 2017. Needs hands-on testing with Python 3.12. If incompatible, fallback is implementing Black-Scholes analytically (straightforward math) or using QuantLib.

3. **LangGraph + PydanticAI integration patterns** -- Both are young libraries. The exact integration pattern (PydanticAI agents as LangGraph nodes) needs prototyping in Phase 1.

4. **WebSocket scaling** -- FastAPI WebSocket connections to multiple dashboard clients while the trading engine processes market data. Need to verify single-process can handle both, or if trading engine and API server must be separate processes (likely yes).

5. **TimescaleDB continuous aggregates for options data** -- Need to prototype the schema for storing and querying options chain snapshots efficiently. This is phase-specific research for the data layer.

---

## Sources

### HIGH Confidence (PyPI / Official Documentation)
- [ib_async on PyPI](https://pypi.org/project/ib_async/) -- v2.1.0, verified 2026-03-25
- [ib_async GitHub](https://github.com/ib-api-reloaded/ib_async) -- README, features, Python requirements
- [ib_async Documentation](https://ib-api-reloaded.github.io/ib_async/) -- v2.1.0 docs
- [LangGraph on PyPI](https://pypi.org/project/langgraph/) -- v1.1.3, verified 2026-03-25
- [PydanticAI on PyPI](https://pypi.org/project/pydantic-ai/) -- v1.71.0, verified 2026-03-25
- [FastAPI on PyPI](https://pypi.org/project/fastapi/) -- v0.135.2, verified 2026-03-25
- [SQLAlchemy on PyPI](https://pypi.org/project/sqlalchemy/) -- v2.0.48, verified 2026-03-25
- [Alembic on PyPI](https://pypi.org/project/alembic/) -- v1.18.4, verified 2026-03-25
- [Redis on PyPI](https://pypi.org/project/redis/) -- v7.4.0, verified 2026-03-25
- [structlog on PyPI](https://pypi.org/project/structlog/) -- v25.5.0, verified 2026-03-25
- [pydantic-settings on PyPI](https://pypi.org/project/pydantic-settings/) -- v2.13.1, verified 2026-03-25
- [anthropic on PyPI](https://pypi.org/project/anthropic/) -- v0.86.0, verified 2026-03-25
- [openai on PyPI](https://pypi.org/project/openai/) -- v2.29.0, verified 2026-03-25
- [uvicorn on PyPI](https://pypi.org/project/uvicorn/) -- v0.42.0, verified 2026-03-25
- [IBKR TWS API Documentation](https://interactivebrokers.github.io/tws-api/introduction.html)
- [IBKR API Solutions](https://www.interactivebrokers.com/en/trading/ib-api.php)
- [Next.js 16 Blog Post](https://nextjs.org/blog/next-16)
- [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/)

### MEDIUM Confidence (Multiple WebSearch sources agree)
- [LangGraph Multi-Agent Architecture Guide (Latenode)](https://latenode.com/blog/ai-frameworks-technical-infrastructure/langgraph-multi-agent-orchestration/langgraph-ai-framework-2025-complete-architecture-guide-multi-agent-orchestration-analysis) -- LangGraph production patterns
- [Building a Multi-Agent AI Trading System (Medium)](https://medium.com/@ishveen/building-a-multi-agent-ai-trading-system-technical-deep-dive-into-architecture-b5ba216e70f3) -- Trading agent architecture
- [TimescaleDB vs QuestDB (QuestDB Blog)](https://questdb.com/blog/timescaledb-vs-questdb-comparison/) -- Performance benchmarks
- [Event-Driven Architecture in Python for Trading (PyQuantNews)](https://www.pyquantnews.com/free-python-resources/event-driven-architecture-in-python-for-trading) -- Asyncio patterns
- [AI Agent Frameworks Comparison 2025 (Langflow)](https://www.langflow.org/blog/the-complete-guide-to-choosing-an-ai-agent-framework-in-2025) -- Framework comparison
- [Best AI Agent Frameworks 2025 (LangWatch)](https://langwatch.ai/blog/best-ai-agent-frameworks-in-2025-comparing-langgraph-dspy-crewai-agno-and-more) -- Framework comparison
- [Redis vs RabbitMQ (AWS)](https://aws.amazon.com/compare/the-difference-between-rabbitmq-and-redis/) -- Message broker comparison

### LOW Confidence (Single source, needs validation)
- [LangGraph latency benchmarks](https://dev.to/saivishwak/benchmarking-ai-agent-frameworks-in-2026-autoagents-rust-vs-langchain-langgraph-llamaindex-338f) -- Claims about LangGraph overhead numbers. Benchmarks from third party, not official.
- [py_vollib_vectorized](https://github.com/marcdemers/py_vollib_vectorized) -- Works but unmaintained since 2021. Needs hands-on Python 3.12 testing.
- [IB Gateway Docker image](https://github.com/gnzsnz/ib-gateway-docker) -- Community maintained, not official IB. Quality unknown.
