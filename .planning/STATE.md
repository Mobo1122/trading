# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-25)

**Core value:** The agents find and execute profitable options trades autonomously while never violating the user's risk constraints
**Current focus:** Phase 5 - Core Agent Pipeline

## Current Position

Phase: 5 of 8 (Core Agent Pipeline)
Plan: 1 of 7 in current phase
Status: In progress
Last activity: 2026-04-04 -- Completed 05-01-PLAN.md (agent foundation)

Progress: [#####-----] 53% (22/42 plans complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 22
- Average duration: 3min
- Total execution time: 1.31 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-ib-connectivity | 6/6 | 22min | 4min |
| 02-market-data-analytics | 5/5 | 19min | 4min |
| 03-risk-engine | 6/6 | 24min | 4min |
| 04-order-execution | 4/4 | 15min | 4min |
| 05-core-agent-pipeline | 1/7 | 5min | 5min |

**Recent Trend:**
- Last 5 plans: 04-01 (3min), 04-02 (3min), 04-03 (4min), 04-04 (5min), 05-01 (5min)
- Trend: consistent

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Safety before intelligence -- Phases 1-4 build foundation before any AI agent runs
- [Roadmap]: Deterministic risk gate before LLM risk assessment -- Phase 3 is pure rules, LLM tier added in Phase 5
- [Roadmap]: Execution layer tested independently of agents -- Phase 4 validates order path before agents can use it
- [01-01]: Used pyaml-env for YAML env var interpolation instead of custom loader
- [01-01]: Invalid TRADING_MODE values silently fall back to paper (safety over error)
- [01-01]: Startup banner at warning level to ensure always visible
- [01-01]: Used hatchling build backend for src/ layout
- [01-03]: Used asyncio.create_task (not ensure_future) for reconnection scheduling
- [01-03]: Random jitter 0-1s added to backoff to prevent thundering herd
- [01-03]: MockEvent test helper for ib_async event handler verification
- [01-02]: TimescaleDB hypertable via raw SQL in migration, not sqlalchemy-timescaledb dialect
- [01-02]: OrderStateTransition uses autoincrement id alongside timestamp for hypertable compatibility
- [01-02]: Redis client with decode_responses=True for string returns
- [01-02]: Session factory uses expire_on_commit=False for post-commit attribute access
- [01-04]: Cache errors are non-fatal -- log warning, continue without cache
- [01-04]: OptionChain fields handled as lists with list() for ib_async version compatibility
- [01-04]: Empty qualify_options input returns immediately without IB API call
- [01-05]: Used current_state_value (not deprecated current_state.value) for python-statemachine v3
- [01-05]: Structlog 'trigger' keyword replaces 'event' to avoid reserved name conflict
- [01-05]: handle_ib_status catches TransitionNotAllowed and returns current state (idempotent)
- [01-06]: connect_ib() separated from startup() so tests run without IB Gateway
- [01-06]: Health levels: HEALTHY (all up), DEGRADED (IB down), UNHEALTHY (DB or Redis down)
- [01-06]: KillSwitch cancels all orders before closing positions (safety sequence)
- [01-06]: Shutdown error isolation: each cleanup step try/excepted independently
- [02-01]: EarningsEvent is regular table (not hypertable) -- not high-frequency time-series data
- [02-01]: MarketQuote stores aggregate fields; per-leg option data in OptionGreeks
- [02-01]: Followed Phase 1 autoincrement-id pattern for hypertable compatibility
- [02-01]: Finnhub API key via pyaml-env !ENV syntax with empty default (non-fatal if unset)
- [02-02]: LRU eviction removes oldest non-pinned subscription; HIGH priority pins never evicted
- [02-02]: Redis dual-write: pub/sub for streaming + HSET for latest-value lookup
- [02-02]: Atomic buffer swap in TimescaleDBWriter prevents data loss during flush
- [02-02]: All timestamps use timezone-aware datetime.now(timezone.utc) instead of utcnow()
- [02-03]: Conservative IB rate limits: 55/window (vs 60 max), 2.5s spacing (vs 2s min)
- [02-03]: Minimum 20 data points for IV rank/percentile; returns None below threshold (cold start safety)
- [02-03]: Sequential watchlist bootstrap to respect IB pacing; asyncio.gather only for DB reads
- [02-03]: Used timezone-aware datetime.now(tz=timezone.utc) instead of deprecated utcnow()
- [02-04]: EarningsCalendar tries finnhub SDK first, falls back to httpx direct API
- [02-04]: Earnings refresh is daily (24h staleness check); cache in-memory per symbol
- [02-04]: Store earnings via upsert (ON CONFLICT DO UPDATE) for idempotent refresh
- [02-05]: Phase 2 components wired but not started until connect_ib() (test-friendly)
- [02-05]: IV bootstrap and earnings refresh are non-critical (try/except with warning)
- [02-05]: Shutdown order: staleness -> market data -> IB disconnect (writer flush needs DB)
- [03-01]: timezone-aware datetime.now(timezone.utc) for RiskDecision.evaluated_at default factory
- [03-01]: risk_decisions and circuit_breaker_state are regular tables (not hypertables) -- low-frequency events
- [03-01]: Paper limits 2x live limits in YAML defaults -- relaxed for testing, strict for live
- [03-02]: existing_positions typed as list[TradeLeg] to reuse existing model instead of new Position type
- [03-03]: Round aggregated Greeks to 10 decimal places to avoid IEEE 754 float noise in comparisons
- [03-03]: evaluate_greeks_exposure returns None on pass, RiskDecision on failure (none-passthrough pattern)
- [03-04]: Upsert via select+update/insert instead of session.merge() for clearer control flow with autoincrement PKs
- [03-04]: emergency_halt accepted as constructor param rather than re-reading config on each check()
- [03-04]: Daily/weekly resets keyed by date string comparison in Redis for idempotent reset
- [03-05]: Per-leg margin checks rather than combo orders (RESEARCH.md recommendation, conservative but safe)
- [03-05]: Persistence errors non-fatal in RiskManager._persist (log warning, continue evaluation)
- [03-05]: First leg with contract/order gets margin check (simple initial approach)
- [03-06]: Risk engine components created in startup(), IB ref set in connect_ib() (same Phase 2 pattern)
- [03-06]: Circuit breaker load_from_db is non-critical (try/except with warning, matches Phase 2 bootstrap pattern)
- [04-01]: Round slippage values to 10 decimal places for IEEE 754 float noise (consistent with 03-03 Greeks pattern)
- [04-04]: Phase 4 follows same lifecycle pattern as Phase 2/3: create in startup(), non-critical bootstrap in connect_ib()
- [04-04]: Order recovery is non-critical (try/except with warning) matching circuit breaker bootstrap pattern
- [04-04]: FillTracker wired via property setter to break circular dependency during construction
- [05-01]: Used pydantic-ai-slim[anthropic] instead of full pydantic-ai to avoid Logfire dependency
- [05-01]: PipelineState uses list[dict] (not Pydantic models) for LangGraph checkpoint serialization
- [05-01]: Checkpoint factory validates psycopg connection string (rejects +asyncpg)
- [05-01]: LangGraph checkpoint tables excluded from Alembic autogenerate via include_object filter
- [05-01]: agent_decision_log is regular table (not hypertable) -- low-frequency audit events

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: py_vollib Python 3.12 compatibility needs hands-on verification (last release 2017)
- [Phase 1]: IB Gateway Docker image is community-maintained, not official -- stability unknown
- [Phase 1]: IB market data subscription costs need audit ($30-100/month for real-time US options)
- [Phase 1]: Docker not installed on dev machine -- Docker Compose validated via YAML parser only
- [Phase 5]: LangGraph + PydanticAI combined integration pattern has sparse documentation -- needs prototyping spike

## Session Continuity

Last session: 2026-04-04
Stopped at: Completed 05-01-PLAN.md (agent foundation). Next: 05-02-PLAN.md.
Resume file: None
