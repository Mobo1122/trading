# Milestone v1: Options Trading AI Agents

**Status:** SHIPPED 2026-04-05
**Phases:** 1-10
**Total Plans:** 45

## Overview

This roadmap delivered an autonomous options trading system in 10 phases, ordered by the principle that safety infrastructure must precede intelligence. Phases 1-4 built the bulletproof foundation (IB connectivity, market data, risk engine, order execution) that can operate safely even if every AI agent fails. Phases 5-6 layered in the multi-agent intelligence pipeline. Phases 7-8 added visibility (dashboard) and human-in-the-loop autonomy (alerts, approval workflows). Phases 9-10 closed integration gaps discovered by milestone audit. Every phase delivered a coherent, independently verifiable capability.

## Phases

### Phase 1: IB Connectivity & Infrastructure

**Goal**: The system reliably connects to Interactive Brokers, retrieves contract data, tracks connection state, and provides the foundational infrastructure (database, cache, configuration) that all subsequent phases build on
**Depends on**: Nothing (first phase)
**Requirements**: CONN-01, CONN-04, CONN-05, CONN-06
**Success Criteria**:
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
**Success Criteria**:
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
**Success Criteria**:
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
**Success Criteria**:
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
**Success Criteria**:
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
**Success Criteria**:
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
**Success Criteria**:
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
**Success Criteria**:
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

### Phase 9: Integration Fixes & Tech Debt

**Goal**: Fix the 3 critical cross-phase wiring gaps discovered by milestone audit (Redis namespace mismatch, circuit breaker dead code, health monitor property) and resolve all tracked tech debt items so the system operates correctly end-to-end
**Depends on**: Phase 8 (all prior phases complete)
**Requirements**: AGENT-01, AGENT-02, AGENT-07, RISK-03, RISK-07, DASH-05
**Gap Closure**: Closes all gaps from v1-MILESTONE-AUDIT.md
**Success Criteria**:
  1. Agents (scanner, strategist, regime detector) read live market data from the correct Redis namespace and receive non-empty price context at runtime
  2. Realized losses from filled trades automatically accumulate in the circuit breaker, triggering daily/weekly loss-limit halts when thresholds are breached
  3. Dashboard pipeline status reflects actual system health (not permanently "idle")
  4. Portfolio realized P&L is tracked and displayed on the dashboard
  5. All tech debt items from the milestone audit are resolved (timing bug, missing test, documentation mismatches)
**Plans**: 2 plans

Plans:
- [x] 09-01-PLAN.md — Fix Redis namespace mismatch in scanner, strategist, and regime detector; wire FillTracker → CircuitBreaker for loss accumulation; fix HealthMonitor.current_health property
- [x] 09-02-PLAN.md — Dashboard realized P&L writer, regime detector timing fix, missing commission test, documentation cleanup

### Phase 10: Position Rolling Pipeline & Alert Polish

**Goal**: Expiring positions are automatically rolled via the agent pipeline, and trade rejection alerts use structured Slack formatting instead of plain text
**Depends on**: Phase 9 (all prior phases complete)
**Requirements**: AGENT-08
**Gap Closure**: Closes all remaining gaps from v1-MILESTONE-AUDIT.md
**Success Criteria**:
  1. Pipeline reads rolling_candidates from PipelineState and routes expiring positions through the strategist for roll construction
  2. ExpirationMonitor.evaluate_rolling() and build_roll_proposals() are called during pipeline execution (no longer dead code)
  3. End-to-end flow works: expiring position → ExpirationMonitor → rolling_candidates → pipeline node → strategist → risk → executor
  4. SlackNotifier formats trade_rejected events with structured Block Kit messages (not plain text fallback)
**Plans**: 1 plan

Plans:
- [x] 10-01-PLAN.md — Rolling pipeline node, ExpirationMonitor activation, and Slack trade_rejected handler

## Progress

**Execution Order:**
Phases executed in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10

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
| 9. Integration Fixes & Tech Debt | 2/2 | Complete | 2026-04-05 |
| 10. Position Rolling Pipeline & Alert Polish | 1/1 | Complete | 2026-04-05 |

---

## Milestone Summary

**Key Decisions:**

- Safety before intelligence — Phases 1-4 build bulletproof foundation before any AI agent runs
- Deterministic risk gate before LLM risk assessment — Phase 3 is pure rules, LLM tier added in Phase 5
- PydanticAI + LangGraph for agent orchestration — clean dependency injection and checkpoint persistence
- Deterministic regime detection (not ML) — testability and auditability critical for real-money system
- Closure-based pipeline routing for three-way approval gate — needed deps access for threshold checks
- Property setter injection pattern for cross-component wiring (FillTracker.circuit_breaker)

**Issues Resolved:**

- Redis namespace mismatch between Phase 2 (mktdata:latest:quote:) and Phase 5 agents (market_data:) — fixed in Phase 9
- FillTracker → CircuitBreaker wiring gap (realized losses never accumulated) — fixed in Phase 9
- HealthMonitor.current_health property missing from DashboardPublisher — fixed in Phase 9
- Rolling pipeline dead code (ExpirationMonitor methods never called) — fixed in Phase 10
- Slack trade_rejected plain text fallback — fixed in Phase 10

**Technical Debt Carried Forward:**

- alerts:trade_executed Slack payload uses proposal_id (UUID) in symbol field instead of ticker
- alerts:system_error channel has narrow publisher coverage (pipeline failures and approval errors only)
- GET /api/health simple endpoint is dead code (frontend uses /api/health/status)
- ContractResolver not instantiated in TradingApp (by design — on-demand utility)
- Runtime confirmation pending: Docker/IB Gateway for TimescaleDB migration, auto-reconnect, futures chains

---

_For current project status, see .planning/PROJECT.md_
