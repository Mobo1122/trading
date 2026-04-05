# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-25)

**Core value:** The agents find and execute profitable options trades autonomously while never violating the user's risk constraints
**Current focus:** Phase 8 - Alerts & Autonomy

## Current Position

Phase: 8 of 8 (Alerts & Autonomy)
Plan: 2 of 5 in current phase
Status: In progress
Last activity: 2026-04-05 -- Completed 08-02-PLAN.md (Approval Manager)

Progress: [################### ] 93% (39/42 plans complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 39
- Average duration: 4min
- Total execution time: 2.58 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-ib-connectivity | 6/6 | 22min | 4min |
| 02-market-data-analytics | 5/5 | 19min | 4min |
| 03-risk-engine | 6/6 | 24min | 4min |
| 04-order-execution | 4/4 | 15min | 4min |
| 05-core-agent-pipeline | 7/7 | 30min | 4min |
| 06-advanced-agent-intelligence | 3/3 | 14min | 5min |
| 07-dashboard-monitoring | 6/6 | 39min | 7min |
| 08-alerts-autonomy | 2/5 | 6min | 3min |

**Recent Trend:**
- Last 5 plans: 07-05 (5min), 07-04 (6min), 07-06 (8min), 08-01 (3min), 08-02 (3min)
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
- [05-02]: Per-symbol tool calls (not batch) let the LLM decide which symbols to query
- [05-02]: UsageLimits defaults from AgentConfig, not hardcoded (single source of truth)
- [05-02]: Redis lookup uses HGETALL on market_data:{symbol} matching Phase 2 dual-write pattern
- [05-03]: Strategist request_limit defaults to 15 (vs scanner's 10) because more tool calls per opportunity
- [05-03]: Option chain tool returns full strikes/expirations without truncation for accurate strike selection
- [05-04]: Symbol-based Greeks matching via Redis SCAN (not con_id) as known simplification for portfolio exposure
- [05-04]: Temperature 0.1 for risk agent (qualitative flexibility), 0.0 for executor (pure execution)
- [05-04]: _lookup_greeks is private async helper shared between tool and internal check_deterministic_risk logic
- [05-05]: Node functions bind PipelineDeps via functools.partial (not lambda) for proper pickling/checkpointing
- [05-05]: Pipeline short-circuits to END after scanner (no opportunities) and after risk (no approvals)
- [05-05]: run_pipeline generates uuid4 thread_id for checkpoint isolation per run
- [05-06]: Logging errors are non-fatal (try/except wrapper, matches 03-05/04-03 pattern)
- [05-06]: model_name left as None since PydanticAI Usage object does not expose it
- [05-06]: Input summaries are descriptive strings per node rather than raw serialized data
- [05-07]: Pipeline deps created in startup(), pipeline compiled in connect_ib() (consistent with Phase 2-4 pattern)
- [05-07]: Non-critical pipeline compilation: try checkpointed, fallback to no-checkpoint
- [05-07]: ContractResolver/ContractCache wired into PipelineDeps for strategist tools
- [06-01]: Deterministic regime detection (not ML) for testability and auditability in real-money system
- [06-01]: Hysteresis prevents regime whiplash -- must persist N consecutive checks before switching
- [06-01]: VIX asymmetric influence -- can upgrade volatility to high but only downgrades from normal
- [06-01]: RegimeClassification co-located in regime.py with RegimeDetector (domain model with producer)
- [06-01]: PipelineState pre-extended with rolling_candidates/rolling_decisions for Plan 02
- [06-02]: Deterministic rolling logic (no LLM) -- safety-critical position management must be predictable
- [06-02]: Close-before-roll safety rule -- positions exceeding max_loss_multiple closed, not rolled
- [06-02]: Any-typed IB reference in ExpirationMonitor for test isolation (same as other agents)
- [06-03]: Regime context injected via prompt_prefix parameter, not agent instruction modification
- [06-03]: Rolling pre-check in app.run_agent_pipeline(), not inside pipeline node (cleaner separation)
- [06-03]: Regime detection errors return empty dict -- scanner runs without regime context (non-fatal)
- [07-01]: FastAPI app factory pattern with async lifespan context manager for resource management
- [07-01]: RedisBridge uses per-channel throttling with atomic buffer swap to prevent flooding clients
- [07-01]: DashboardPublisher uses SCAN (not KEYS) for Redis key enumeration (production safety)
- [07-01]: Portfolio Greeks aggregated by summing across all mktdata:latest:greeks:* keys with rounding to 10dp
- [07-01]: Dashboard publisher non-critical in TradingApp (try/except with warning, matching Phase 2-6 bootstrap pattern)
- [07-01]: get_db_session as FastAPI Depends generator (same commit/rollback pattern as trading.db.session.get_session)
- [07-02]: Skipped shadcn chart component (depends on recharts, deferred to later plan)
- [07-02]: Root page redirects to /positions instead of rendering dashboard home
- [07-02]: WebSocket client uses class singleton pattern, not React context
- [07-02]: Server/Client boundary: root layout is Server Component, interactivity in child client components
- [07-03]: P&L multiplier: 100x for options (OPT), 1x for stocks (STK) -- standard contract sizing
- [07-03]: Price source: last price preferred, fallback to bid/ask midpoint
- [07-03]: Portfolio /api/portfolio calls /api/positions internally to aggregate -- single source of truth
- [07-03]: Net liquidation = market_value + unrealized_pnl + realized_pnl (additive formula)
- [07-04]: Fixed proposal_id/run_id linkage: ExecutorDeps.run_id flows from PipelineState to TradeProposal.proposal_id
- [07-04]: Greeks thresholds hardcoded (delta>500=yellow, >1000=red) matching risk_limits patterns
- [07-04]: Trades endpoint uses per-order reasoning chain query (N+1) for simplicity at current scale
- [07-04]: api.ts getTradeHistory updated to return {trades, total} envelope for pagination metadata
- [07-05]: Extract get_db_session to deps.py to break circular import between server.py and route modules
- [07-05]: Agent last-seen thresholds: 10min stale (yellow), 1hr inactive (red) for agent activity display
- [07-06]: scipy.stats.norm.cdf for Black-Scholes CDF (standard, well-tested implementation)
- [07-06]: Default IV of 0.25 (25%) when implied volatility unavailable from Redis or position data
- [07-06]: OCC symbol parsing as fallback for contract detail resolution when Redis cache misses
- [07-06]: ScenarioPositionResult typed interface instead of unknown[] for per-position results
- [08-01]: Added aiohttp as explicit dependency (required by slack-sdk AsyncWebhookClient at import time)
- [08-01]: AlertRouter uses exact subscribe (not psubscribe) for precise channel matching
- [08-01]: Monotonic timestamps for SMS cooldown (immune to system clock adjustments)
- [08-01]: Independent try/except per notifier in AlertRouter._route (one failure must not block the other)
- [08-02]: asyncio.wait (not wait_for) with explicit listener_task for clean cancellation on both timeout and cross-process resolution paths
- [08-02]: Redis key TTL = timeout + 3600s for dashboard visibility after expiration
- [08-02]: scan_iter (not KEYS) for get_pending -- production-safe Redis enumeration
- [08-02]: Approval lifecycle: Redis hash persistence + asyncio.Future in-process signaling + pub/sub cross-process resolution

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: py_vollib Python 3.12 compatibility needs hands-on verification (last release 2017)
- [Phase 1]: IB Gateway Docker image is community-maintained, not official -- stability unknown
- [Phase 1]: IB market data subscription costs need audit ($30-100/month for real-time US options)
- [Phase 1]: Docker not installed on dev machine -- Docker Compose validated via YAML parser only
- [Phase 5]: LangGraph + PydanticAI integration validated in code -- sparse documentation concern resolved

## Session Continuity

Last session: 2026-04-05
Stopped at: Completed 08-02-PLAN.md (Approval Manager). Phase 8 in progress (2/5 plans).
Resume file: None
