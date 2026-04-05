# Roadmap: Options Trading AI Agents

## Overview

This roadmap delivers an autonomous options trading system in 8 phases, ordered by the principle that safety infrastructure must precede intelligence. Phases 1-4 build the bulletproof foundation (IB connectivity, market data, risk engine, order execution) that can operate safely even if every AI agent fails. Phases 5-6 layer in the multi-agent intelligence pipeline. Phases 7-8 add visibility (dashboard) and human-in-the-loop autonomy (alerts, approval workflows). Every phase delivers a coherent, independently verifiable capability.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: IB Connectivity & Infrastructure** - Establish reliable IB Gateway connection, project scaffolding, database, and paper/live toggle
- [x] **Phase 2: Market Data & Analytics** - Stream real-time quotes, Greeks, and IV with analytical overlays for trade decision support
- [x] **Phase 3: Risk Engine** - Enforce all risk constraints deterministically before any trade can execute
- [x] **Phase 4: Order Execution** - Place and track single-leg and multi-leg orders through the risk gate to IB
- [x] **Phase 5: Core Agent Pipeline** - Wire scanner, strategist, risk manager, and executor agents into a LangGraph-orchestrated pipeline
- [x] **Phase 6: Advanced Agent Intelligence** - Add market regime awareness and automated position rolling to the agent pipeline
- [x] **Phase 7: Dashboard & Monitoring** - Provide full visibility into positions, P&L, Greeks, agent reasoning, and system health via web dashboard
- [x] **Phase 8: Alerts & Autonomy** - Enable autonomous small-trade execution, human approval workflows, and real-time alerting

## Phase Details

### Phase 1: IB Connectivity & Infrastructure
**Goal**: The system reliably connects to Interactive Brokers, retrieves contract data, tracks connection state, and provides the foundational infrastructure (database, cache, configuration) that all subsequent phases build on
**Depends on**: Nothing (first phase)
**Requirements**: CONN-01, CONN-04, CONN-05, CONN-06
**Success Criteria** (what must be TRUE):
  1. System connects to IB Gateway on startup and automatically reconnects after disconnection or daily restart without manual intervention
  2. User can switch between paper and live trading by changing a single configuration value, with no code changes required
  3. System retrieves complete option chains (all strikes, expirations, contract specs) for any equity, ETF, or futures underlying
  4. Every order state transition (pending, submitted, filled, cancelled, error) is tracked in a local state machine and persisted to the database
  5. PostgreSQL, TimescaleDB, and Redis are running and accessible, with schema migrations applied
**Plans**: 6 plans

Plans:
- [x] 01-01-PLAN.md — Project scaffolding, dependencies, config system, Docker Compose, paper/live toggle
- [x] 01-02-PLAN.md — PostgreSQL + TimescaleDB schema, Alembic migrations, Redis client
- [x] 01-03-PLAN.md — IB Gateway connection manager with auto-reconnect and exponential backoff
- [x] 01-04-PLAN.md — Option chain retrieval via reqSecDefOptParams with Redis caching
- [x] 01-05-PLAN.md — Order state machine (python-statemachine) with DB persistence and IB status mapping
- [x] 01-06-PLAN.md — Kill switch, health monitoring, and application lifecycle wiring

### Phase 2: Market Data & Analytics
**Goal**: Real-time market data streams from IB into the system, providing quotes, Greeks, IV, and analytical metrics that downstream agents and the risk engine depend on
**Depends on**: Phase 1
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05
**Success Criteria** (what must be TRUE):
  1. System streams real-time bid/ask, last price, and volume for subscribed underlyings and options contracts
  2. System streams real-time per-contract Greeks (delta, gamma, theta, vega) and implied volatility from IB
  3. Open interest and volume data is available per options contract for liquidity filtering
  4. IV rank and IV percentile vs 52-week history is calculated and available for any underlying
  5. Upcoming earnings dates are identified and the system flags underlyings approaching earnings events for IV expansion/crush awareness
**Plans**: 5 plans

Plans:
- [x] 02-01-PLAN.md — Pydantic data models, TimescaleDB schema (market_quotes, option_greeks, iv_history, earnings_events), and MarketDataConfig
- [x] 02-02-PLAN.md — Subscription manager (100-line limit, LRU eviction), Redis distributor (pub/sub + HSET), streaming engine, batch DB writer, staleness monitor
- [x] 02-03-PLAN.md — IV rank/percentile engine with IB historical data bootstrap, rate limiting, and cached computation
- [x] 02-04-PLAN.md — Finnhub earnings calendar integration with daily refresh and earnings flags
- [x] 02-05-PLAN.md — App lifecycle wiring for all Phase 2 components and comprehensive unit tests

### Phase 3: Risk Engine
**Goal**: A deterministic risk management layer enforces all position, exposure, and loss constraints independently of any AI component, and blocks all trading when the risk gate is unreachable
**Depends on**: Phase 2
**Requirements**: RISK-01, RISK-02, RISK-03, RISK-04, RISK-05, RISK-06, RISK-07
**Success Criteria** (what must be TRUE):
  1. System rejects any trade that would exceed configurable position sizing limits (max percentage of portfolio, max contracts, max dollar amount per trade)
  2. System rejects any trade that would push portfolio-level Greeks (delta, gamma, theta, vega) beyond configurable exposure caps
  3. System halts all new trading when daily or weekly realized loss limits are breached, and this halt persists across system restarts
  4. System rejects trades that violate strategy restrictions (e.g., naked options blocked when not on the allowlist)
  5. When the risk manager process is unreachable or unresponsive, zero trades execute (fail-safe default)
**Plans**: 6 plans

Plans:
- [x] 03-01-PLAN.md — Risk domain models, config with paper/live limits, ORM schema, Alembic migration 003
- [x] 03-02-PLAN.md — Position sizing evaluator and strategy restriction/naked options evaluator
- [x] 03-03-PLAN.md — Portfolio Greeks aggregation and exposure limit evaluator
- [x] 03-04-PLAN.md — Circuit breaker with loss limits, Redis+Postgres dual storage, auto-reset
- [x] 03-05-PLAN.md — RiskManager orchestrator, whatIfOrder margin check, fail-safe wrapper
- [x] 03-06-PLAN.md — App lifecycle wiring and comprehensive unit tests for all risk rules

### Phase 4: Order Execution
**Goal**: The system can place single-leg and multi-leg options orders through IB, with every order passing through the risk gate and every fill tracked end-to-end
**Depends on**: Phase 3
**Requirements**: CONN-02, CONN-03
**Success Criteria** (what must be TRUE):
  1. System places market, limit, and stop orders for options contracts via IB API, with fills confirmed and recorded
  2. System places multi-leg combo/spread orders (up to 6 legs) as a single atomic order to IB
  3. Orders submitted through the system are validated by the risk engine before reaching IB
  4. Fill tracking records execution price, slippage vs expected, and timestamps for every order
**Plans**: 4 plans

Plans:
- [x] 04-01-PLAN.md — ExecutionRecord DB schema, Pydantic execution models, and ComboOrderBuilder
- [x] 04-02-PLAN.md — OrderExecutionService with risk-gated single-leg and multi-leg order submission
- [x] 04-03-PLAN.md — FillTracker for event-driven fill recording and OrderRecoveryManager for reconnect reconciliation
- [x] 04-04-PLAN.md — App lifecycle wiring and comprehensive unit tests for all execution components

### Phase 5: Core Agent Pipeline
**Goal**: A pipeline of AI agents (scanner, strategist, risk manager, executor) autonomously finds options opportunities, constructs trade proposals, validates them against risk rules, and executes approved trades -- with every decision logged in natural language
**Depends on**: Phase 4
**Requirements**: AGENT-01, AGENT-02, AGENT-03, AGENT-04, AGENT-05, AGENT-06
**Success Criteria** (what must be TRUE):
  1. Scanner agent identifies options trading opportunities across equities, ETFs, and futures based on market data and analytics
  2. Strategist agent takes scanner output and constructs complete trade proposals (strategy type, strikes, expirations, sizing)
  3. Risk manager agent validates trade proposals against all deterministic rules and adds LLM-based risk assessment
  4. Executor agent routes validated trades to IB for execution via the order execution layer
  5. The full pipeline runs as scanner -> strategist -> risk manager -> executor via LangGraph, with state persistence between nodes
**Plans**: 7 plans

Plans:
- [x] 05-01-PLAN.md — PydanticAI + LangGraph dependencies, agent config, shared output contracts, pipeline state, checkpoint factory, DB migration
- [x] 05-02-PLAN.md — Scanner agent with IV analytics, earnings, and market data tools
- [x] 05-03-PLAN.md — Strategist agent with option chain lookup and risk-aware trade construction
- [x] 05-04-PLAN.md — Risk manager agent (deterministic-first) and executor agent (OrderExecutionService wrapper)
- [x] 05-05-PLAN.md — LangGraph StateGraph pipeline orchestration with conditional routing and checkpoints
- [x] 05-06-PLAN.md — Agent decision logging with full reasoning chain DB persistence
- [x] 05-07-PLAN.md — App lifecycle wiring and comprehensive unit tests for all agent components

### Phase 6: Advanced Agent Intelligence
**Goal**: The agent pipeline adapts to market conditions by detecting regimes and automatically manages expiring positions through rolling
**Depends on**: Phase 5
**Requirements**: AGENT-07, AGENT-08
**Success Criteria** (what must be TRUE):
  1. Scanner detects the current market regime (bull, bear, sideways, volatile) and the strategy mix adapts accordingly
  2. System identifies positions approaching expiration and automatically rolls them to new expirations when appropriate
  3. Regime changes and rolling decisions are logged with full reasoning, visible in the agent decision log
**Plans**: 3 plans

Plans:
- [x] 06-01-PLAN.md — Deterministic regime detection module with MarketRegime enum, RegimeDetector, strategy weight mapping, and RegimeConfig
- [x] 06-02-PLAN.md — ExpirationMonitor with position scanning, rolling criteria evaluation, and RollingConfig
- [x] 06-03-PLAN.md — Pipeline integration (regime node, scanner prompt injection, rolling pre-check), app wiring, and comprehensive tests

### Phase 7: Dashboard & Monitoring
**Goal**: A web dashboard provides full real-time visibility into every aspect of the trading system -- positions, P&L, Greeks, agent reasoning, system health, and scenario analysis
**Depends on**: Phase 5
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06
**Success Criteria** (what must be TRUE):
  1. Dashboard displays all open positions with real-time per-position and portfolio-level P&L
  2. Dashboard displays portfolio-level aggregated Greeks (delta, gamma, theta, vega) updating in real time
  3. Dashboard shows complete trade history with timestamps, fill details, and the agent reasoning chain for each trade
  4. Dashboard shows system health indicators: IB connection status, agent heartbeats, data stream freshness
  5. User can run P&L scenario analysis (what-if: underlying +/- X%, IV +/- Y%, T+N days) from the dashboard
**Plans**: 6 plans

Plans:
- [x] 07-01-PLAN.md — FastAPI WebSocket server with Redis bridge, ChannelManager, Pydantic response models, and DashboardConfig
- [x] 07-02-PLAN.md — Next.js dashboard shell with shadcn/ui, Zustand stores, WebSocket client, and navigation layout
- [x] 07-03-PLAN.md — Positions display with real-time P&L (REST endpoints, positions table, portfolio summary, unit tests)
- [x] 07-04-PLAN.md — Portfolio Greeks display and trade history with agent reasoning chains
- [x] 07-05-PLAN.md — System health monitoring panel (connection status, data freshness, pipeline health)
- [x] 07-06-PLAN.md — P&L scenario analysis engine (Black-Scholes) and interactive dashboard UI

### Phase 8: Alerts & Autonomy
**Goal**: The system operates autonomously for small trades, escalates large trades for human approval with full context, and sends real-time alerts for all significant events
**Depends on**: Phase 5, Phase 7
**Requirements**: AUTO-01, AUTO-02, AUTO-03, AUTO-04, AUTO-05
**Success Criteria** (what must be TRUE):
  1. System sends Slack and/or SMS alerts for trade executions, risk limit breaches, and system errors
  2. Trades below the configurable threshold (dollar amount, Greeks impact) execute automatically without human intervention
  3. Trades above the threshold present an approval request with full trade context (strategy, Greeks impact, max loss scenario) and a clear approve/reject interface
  4. Approval requests that receive no human response within the timeout period are automatically rejected (safe default)
  5. User can approve or reject escalated trades directly from Slack via interactive buttons without opening the dashboard
**Plans**: 5 plans

Plans:
- [x] 08-01-PLAN.md — AlertConfig, SlackNotifier (webhook), SMSNotifier (Twilio via httpx with cooldown), AlertRouter consuming Redis pub/sub events
- [x] 08-02-PLAN.md — ApprovalManager with Redis state, asyncio.Future timeout-to-reject, expired recovery, PipelineState extension
- [x] 08-03-PLAN.md — Pipeline approval gate (threshold routing, background post-approval execution), TradingApp Phase 8 lifecycle wiring
- [x] 08-04-PLAN.md — Dashboard approval UI (REST endpoints, Next.js page with approval cards, Zustand store, WebSocket updates)
- [x] 08-05-PLAN.md — Slack interactive buttons via slack-bolt Socket Mode, Block Kit approve/reject buttons, message update on resolution

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8
Note: Phases 6 and 7 can execute in parallel after Phase 5 completes.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. IB Connectivity & Infrastructure | 6/6 | Complete | 2026-03-26 |
| 2. Market Data & Analytics | 5/5 | Complete | 2026-04-02 |
| 3. Risk Engine | 6/6 | Complete | 2026-04-03 |
| 4. Order Execution | 4/4 | Complete | 2026-04-04 |
| 5. Core Agent Pipeline | 7/7 | Complete | 2026-04-04 |
| 6. Advanced Agent Intelligence | 3/3 | Complete | 2026-04-04 |
| 7. Dashboard & Monitoring | 6/6 | Complete | 2026-04-05 |
| 8. Alerts & Autonomy | 5/5 | Complete | 2026-04-05 |
