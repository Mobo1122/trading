# Roadmap: Options Trading AI Agents

## Overview

This roadmap delivers an autonomous options trading system in 8 phases, ordered by the principle that safety infrastructure must precede intelligence. Phases 1-4 build the bulletproof foundation (IB connectivity, market data, risk engine, order execution) that can operate safely even if every AI agent fails. Phases 5-6 layer in the multi-agent intelligence pipeline. Phases 7-8 add visibility (dashboard) and human-in-the-loop autonomy (alerts, approval workflows). Every phase delivers a coherent, independently verifiable capability.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: IB Connectivity & Infrastructure** - Establish reliable IB Gateway connection, project scaffolding, database, and paper/live toggle
- [ ] **Phase 2: Market Data & Analytics** - Stream real-time quotes, Greeks, and IV with analytical overlays for trade decision support
- [ ] **Phase 3: Risk Engine** - Enforce all risk constraints deterministically before any trade can execute
- [ ] **Phase 4: Order Execution** - Place and track single-leg and multi-leg orders through the risk gate to IB
- [ ] **Phase 5: Core Agent Pipeline** - Wire scanner, strategist, risk manager, and executor agents into a LangGraph-orchestrated pipeline
- [ ] **Phase 6: Advanced Agent Intelligence** - Add market regime awareness and automated position rolling to the agent pipeline
- [ ] **Phase 7: Dashboard & Monitoring** - Provide full visibility into positions, P&L, Greeks, agent reasoning, and system health via web dashboard
- [ ] **Phase 8: Alerts & Autonomy** - Enable autonomous small-trade execution, human approval workflows, and real-time alerting

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
- [ ] 01-01-PLAN.md — Project scaffolding, dependencies, config system, Docker Compose, paper/live toggle
- [ ] 01-02-PLAN.md — PostgreSQL + TimescaleDB schema, Alembic migrations, Redis client
- [ ] 01-03-PLAN.md — IB Gateway connection manager with auto-reconnect and exponential backoff
- [ ] 01-04-PLAN.md — Option chain retrieval via reqSecDefOptParams with Redis caching
- [ ] 01-05-PLAN.md — Order state machine (python-statemachine) with DB persistence and IB status mapping
- [ ] 01-06-PLAN.md — Kill switch, health monitoring, and application lifecycle wiring

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
**Plans**: TBD

Plans:
- [ ] 02-01: Real-time quote streaming via IB with Redis pub/sub distribution
- [ ] 02-02: Greeks and IV streaming with subscription management
- [ ] 02-03: Open interest, volume ingestion, and liquidity metrics
- [ ] 02-04: IV rank/percentile calculation engine with historical data storage
- [ ] 02-05: Earnings calendar integration and IV event flagging

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
**Plans**: TBD

Plans:
- [ ] 03-01: Position sizing rules engine with configurable limits
- [ ] 03-02: Portfolio Greeks aggregation and exposure limit enforcement
- [ ] 03-03: Daily/weekly loss limits with circuit breakers and persistent state
- [ ] 03-04: Strategy restriction allowlist and naked options detection
- [ ] 03-05: Risk manager fail-safe (unreachable = block all trades)
- [ ] 03-06: Pre-trade margin check via IB whatIfOrder API

### Phase 4: Order Execution
**Goal**: The system can place single-leg and multi-leg options orders through IB, with every order passing through the risk gate and every fill tracked end-to-end
**Depends on**: Phase 3
**Requirements**: CONN-02, CONN-03
**Success Criteria** (what must be TRUE):
  1. System places market, limit, and stop orders for options contracts via IB API, with fills confirmed and recorded
  2. System places multi-leg combo/spread orders (up to 6 legs) as a single atomic order to IB
  3. Orders submitted through the system are validated by the risk engine before reaching IB
  4. Fill tracking records execution price, slippage vs expected, and timestamps for every order
**Plans**: TBD

Plans:
- [ ] 04-01: Single-leg order placement (market, limit, stop) with risk gate integration
- [ ] 04-02: Multi-leg combo/spread order construction and submission
- [ ] 04-03: Fill tracking, slippage measurement, and execution audit trail
- [ ] 04-04: IB reconnection recovery for in-flight orders

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
**Plans**: TBD

Plans:
- [ ] 05-01: PydanticAI agent framework setup and structured output contracts
- [ ] 05-02: Scanner agent with parallel sub-scans (technical, fundamental, IV-based)
- [ ] 05-03: Strategist agent with LLM strategy selection and quant strike/pricing
- [ ] 05-04: Risk manager agent (LLM tier layered on deterministic rules)
- [ ] 05-05: Executor agent integration with order execution layer
- [ ] 05-06: LangGraph pipeline orchestration with state persistence and checkpoints
- [ ] 05-07: Agent reasoning chain logging and decision audit trail

### Phase 6: Advanced Agent Intelligence
**Goal**: The agent pipeline adapts to market conditions by detecting regimes and automatically manages expiring positions through rolling
**Depends on**: Phase 5
**Requirements**: AGENT-07, AGENT-08
**Success Criteria** (what must be TRUE):
  1. Scanner detects the current market regime (bull, bear, sideways, volatile) and the strategy mix adapts accordingly
  2. System identifies positions approaching expiration and automatically rolls them to new expirations when appropriate
  3. Regime changes and rolling decisions are logged with full reasoning, visible in the agent decision log
**Plans**: TBD

Plans:
- [ ] 06-01: Market regime detection model and strategy mix adaptation
- [ ] 06-02: Expiration monitoring and automated position rolling logic
- [ ] 06-03: Integration testing of advanced intelligence with full pipeline

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
**Plans**: TBD

Plans:
- [ ] 07-01: FastAPI WebSocket server subscribing to Redis channels
- [ ] 07-02: Next.js dashboard shell with real-time WebSocket state management
- [ ] 07-03: Positions display with real-time P&L (per-position and portfolio)
- [ ] 07-04: Portfolio Greeks display and trade history with reasoning chains
- [ ] 07-05: System health monitoring panel (connection, heartbeats, data freshness)
- [ ] 07-06: P&L scenario analysis engine and dashboard UI

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
**Plans**: TBD

Plans:
- [ ] 08-01: Alert routing system (Slack webhooks + Twilio SMS) consuming Redis events
- [ ] 08-02: Auto-execute threshold configuration and routing logic in executor
- [ ] 08-03: Trade approval workflow with context display and timeout-to-reject
- [ ] 08-04: Dashboard approval UI for escalated trades
- [ ] 08-05: Slack interactive buttons for approve/reject

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8
Note: Phases 6 and 7 can execute in parallel after Phase 5 completes.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. IB Connectivity & Infrastructure | 0/6 | Planning complete | - |
| 2. Market Data & Analytics | 0/5 | Not started | - |
| 3. Risk Engine | 0/6 | Not started | - |
| 4. Order Execution | 0/4 | Not started | - |
| 5. Core Agent Pipeline | 0/7 | Not started | - |
| 6. Advanced Agent Intelligence | 0/3 | Not started | - |
| 7. Dashboard & Monitoring | 0/6 | Not started | - |
| 8. Alerts & Autonomy | 0/5 | Not started | - |
