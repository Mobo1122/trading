# Architecture Patterns

**Domain:** Multi-agent AI-powered options trading system
**Researched:** 2026-03-25
**Overall confidence:** MEDIUM-HIGH

---

## Recommended Architecture

### High-Level Overview

A **composite multi-agent pipeline** combining Google's Sequential Pipeline pattern (for the core trading flow) with Parallel Fan-Out/Gather (for the analysis stage) and Human-in-the-Loop (for trade approval). The system has five architectural layers:

1. **Data Ingestion Layer** -- Market data, news, options chains from IB and external sources
2. **Agent Orchestration Layer** -- LangGraph-managed agent pipeline with shared state
3. **Risk Gate Layer** -- Hard constraint enforcement, circuit breakers, kill switch
4. **Execution Layer** -- IB API integration for order management
5. **Presentation Layer** -- Web dashboard, alerts, audit trail

```
                    +------------------+
                    |  Web Dashboard   |  (React + WebSocket)
                    |  + Alert System  |
                    +--------+---------+
                             |
                    +--------+---------+
                    |   FastAPI Server  |  (REST + WebSocket)
                    +--------+---------+
                             |
         +-------------------+-------------------+
         |           Agent Orchestration          |
         |              (LangGraph)               |
         |                                        |
         |  +----------+    +--------------+      |
         |  | Scanner  |--->| Strategist   |      |
         |  | Agent    |    | Agent        |      |
         |  +----------+    +------+-------+      |
         |       ^                 |              |
         |       |          +------v-------+      |
         |       |          | Risk Manager |      |
         |       |          | Agent        |      |
         |       |          +------+-------+      |
         |       |                 |              |
         |       |          +------v-------+      |
         |       |          | Executor     |      |
         |       |          | Agent        |      |
         |       |          +--------------+      |
         +-------------------+-------------------+
                             |
         +-------------------+-------------------+
         |          Infrastructure Layer           |
         |                                        |
         |  +-------+  +--------+  +-----------+  |
         |  | Redis  |  | Postgres|  | IB API   |  |
         |  | (state |  | + Time |  | (ib_async)|  |
         |  |  bus)  |  | Scale) |  |          |  |
         |  +-------+  +--------+  +-----------+  |
         +----------------------------------------+
```

### Why This Architecture

**Use a pipeline over a mesh:** The trading flow is inherently sequential -- you scan opportunities, formulate strategies, check risk, then execute. A pipeline makes the data flow explicit, debuggable, and auditable. Each agent has a clear input contract and output contract. This directly maps to Google's Sequential Pipeline pattern, which they describe as "linear, deterministic, and refreshingly easy to debug because you always know exactly where the data came from." [Confidence: HIGH -- pattern well-established in both TradingAgents framework and Google's ADK documentation]

**Use LangGraph over CrewAI or bare LangChain:** LangGraph provides graph-based state management where agent interactions are nodes in a directed graph. This gives fine-grained control over state transitions, supports async execution, and natively handles the human-in-the-loop approval pattern through interrupt/resume. The TradingAgents framework (the leading open-source multi-agent trading reference implementation) uses LangGraph for exactly this reason. [Confidence: HIGH -- verified via TradingAgents repo and LangGraph official docs]

**Use an event bus (Redis) alongside the agent pipeline:** The agent pipeline handles the deliberative flow (scan -> strategize -> risk check -> execute). But real-time concerns (market data updates, position changes, alert triggers, dashboard pushes) need a pub/sub event bus. Redis Streams handles both -- message queuing for the agent pipeline and pub/sub for real-time event broadcasting. [Confidence: MEDIUM -- architectural best practice confirmed across multiple sources but specific Redis Streams + LangGraph integration is less documented]

---

## Component Boundaries

### Component 1: Market Data Service

| Attribute | Detail |
|-----------|--------|
| **Responsibility** | Connect to IB, stream real-time quotes, options chains, Greeks. Cache and distribute market data to all consumers. |
| **Technology** | ib_async (v2.1.0) + Redis for caching/pub-sub |
| **Communicates With** | IB Gateway (upstream), Redis (publish), Scanner Agent (consumer), Risk Manager (consumer), Dashboard (consumer) |
| **Key Constraint** | IB limits: 50 messages/second outbound, ~100 simultaneous streaming market data lines (varies by subscription tier). Must batch requests and manage subscriptions intelligently. |
| **Interface** | Publishes tick events to Redis channels. Provides REST endpoint for snapshot requests via FastAPI. |

**Build note:** This is the foundational service. Nothing else works without market data flowing. Build and validate this first.

### Component 2: Scanner Agent

| Attribute | Detail |
|-----------|--------|
| **Responsibility** | Identify trading opportunities. Scan universe of underlyings for setups matching criteria (unusual volume, volatility spikes, technical setups, earnings events). Combine LLM reasoning (news/sentiment analysis) with quant signals (technical indicators, options flow). |
| **Technology** | LangGraph node, LLM calls (for research/sentiment), quantitative screening logic (pandas/numpy) |
| **Communicates With** | Market Data Service (reads), External Data APIs (news, sentiment), Strategist Agent (output) |
| **Input** | Market data ticks, news feeds, options chain snapshots |
| **Output** | `ScanResult` -- a structured object containing: underlying symbol, setup type, supporting evidence (quant signals + LLM reasoning), confidence score, timestamp |
| **Key Design** | Uses Google's Parallel Fan-Out pattern internally: multiple sub-scanners (technical, fundamental, sentiment, options flow) run concurrently, then a synthesizer merges results. This mirrors TradingAgents' Analyst Team pattern. |

### Component 3: Strategist Agent

| Attribute | Detail |
|-----------|--------|
| **Responsibility** | Given a scan result, construct a concrete options strategy. Select strategy type (vertical spread, iron condor, calendar spread, etc.), choose strikes, expirations, and sizing. LLM reasons about market regime and strategy selection; quant models price the trade and evaluate expected value. |
| **Technology** | LangGraph node, LLM calls (strategy reasoning), QuantLib or vollib (options pricing/Greeks), ib_async (options chain queries) |
| **Communicates With** | Scanner Agent (input), Market Data Service (options chains, Greeks), Risk Manager Agent (output) |
| **Input** | `ScanResult` + current options chain data + portfolio context |
| **Output** | `TradeProposal` -- strategy type, legs (each with contract details, action, quantity), entry criteria, target P&L, max loss, estimated Greeks impact, LLM reasoning narrative |
| **Key Design** | The LLM handles "what type of strategy" and "why." The quant models handle "which strikes," "what price," and "what's the expected value." Strict separation prevents LLM hallucination on pricing. |

### Component 4: Risk Manager Agent

| Attribute | Detail |
|-----------|--------|
| **Responsibility** | Evaluate trade proposals against portfolio risk constraints. This is the hardest gate in the system -- if risk says no, the trade does not execute. Checks: position sizing limits, Greeks exposure limits (portfolio delta, theta, vega, gamma), daily/weekly loss limits, strategy restrictions (e.g., no naked options), concentration limits, margin requirements. |
| **Technology** | LangGraph node, deterministic rule engine (primary), LLM (secondary -- for regime assessment and edge case reasoning) |
| **Communicates With** | Strategist Agent (input), Market Data Service (current Greeks, prices), Portfolio State (positions, P&L), Executor Agent (approved proposals) or Dashboard (escalated for human approval) |
| **Input** | `TradeProposal` + current portfolio state + risk parameters |
| **Output** | `RiskDecision` -- approved/rejected/modified/escalated, risk metrics (pre-trade and projected post-trade), adjustment suggestions if modified, escalation reason if human approval needed |
| **Key Design** | **Two-tier architecture**: (1) Deterministic rule engine runs first -- hard limits that cannot be overridden (max position size, Greeks limits, loss limits, no-naked-options rule). (2) LLM-based assessment runs second on proposals that pass hard limits -- evaluates market regime, correlation risks, tail risks. This ensures the system is fail-safe: if the LLM is down, the deterministic rules still enforce safety. |

**Critical constraint:** If the Risk Manager is unreachable, NO trades execute. This is a system invariant, not a preference.

### Component 5: Executor Agent

| Attribute | Detail |
|-----------|--------|
| **Responsibility** | Convert approved trade proposals into IB orders. Handle order lifecycle: submission, fills, partial fills, cancellations, modifications. Implement the hybrid autonomy model: auto-execute below threshold, route to human approval above threshold. |
| **Technology** | LangGraph node, ib_async (order management), state machine for order lifecycle |
| **Communicates With** | Risk Manager Agent (input), IB Gateway (orders), Portfolio State (update on fills), Dashboard (status updates, approval requests), Alert System (trade notifications) |
| **Input** | `RiskDecision` (approved) with `TradeProposal` |
| **Output** | `ExecutionResult` -- order IDs, fill prices, fill quantities, commissions, slippage vs expected |
| **Key Design** | Implements a state machine for each order: PENDING -> SUBMITTED -> PARTIAL_FILL -> FILLED / CANCELLED / ERROR. Handles IB-specific edge cases: order ID management, reconnection after disconnect (IB connections are fragile), paper vs live account routing. |

### Component 6: Portfolio State Manager

| Attribute | Detail |
|-----------|--------|
| **Responsibility** | Single source of truth for current positions, P&L, Greeks exposure, margin usage, cash balance. Reconciles with IB account data. Provides portfolio context to all agents. |
| **Technology** | PostgreSQL (positions, trades, orders), Redis (real-time state cache), ib_async (account updates) |
| **Communicates With** | IB Gateway (account sync), all agents (portfolio context), Dashboard (positions/P&L display), Risk Manager (exposure checks) |
| **Key Design** | **Dual-write pattern**: IB is the authoritative source; local DB is the working copy. On startup and periodically, reconcile local state with IB account state. During operation, update local state optimistically on fills, but always reconcile. This handles the case where IB processes an order but the local system misses the confirmation. |

### Component 7: Web Dashboard + API Server

| Attribute | Detail |
|-----------|--------|
| **Responsibility** | Serve the web dashboard UI. Provide REST API for configuration and commands. Push real-time updates via WebSocket. Handle human approval flow for escalated trades. |
| **Technology** | FastAPI (REST + WebSocket server), React/TypeScript (frontend), Redis (subscribe to events for push) |
| **Communicates With** | All agents (status/reasoning), Portfolio State (positions/P&L), Risk Manager (approval routing), Alert System (event forwarding) |
| **Key Design** | The dashboard is a consumer, not a controller. It reads agent state and displays it. The only write paths are: (1) approve/reject escalated trades, (2) modify risk parameters, (3) trigger paper/live toggle, (4) emergency kill switch. FastAPI WebSocket connections subscribe to Redis channels for real-time push. |

### Component 8: Alert System

| Attribute | Detail |
|-----------|--------|
| **Responsibility** | Send real-time notifications via Slack and/or SMS for trades, risk events, system health issues, and approval requests. |
| **Technology** | Slack API (webhooks), Twilio (SMS), Redis (subscribe to alert events) |
| **Communicates With** | All agents (subscribe to events), Dashboard (mirror alerts) |
| **Key Design** | Simple consumer of the Redis event bus. Each alert type has a severity level and routing rule (e.g., trade fills go to Slack, risk limit breaches go to SMS + Slack, system errors go to SMS). |

---

## Data Flow

### Primary Trading Pipeline (Happy Path)

```
1. MARKET DATA INGESTION
   IB Gateway -> ib_async -> Market Data Service -> Redis (tick channels)

2. OPPORTUNITY SCANNING (triggered by schedule or market events)
   Market Data (Redis) -> Scanner Agent
   External APIs (news, sentiment) -> Scanner Agent
   Scanner Agent -> ScanResult -> LangGraph state

3. STRATEGY FORMULATION
   ScanResult -> Strategist Agent
   Options Chain Data (IB) -> Strategist Agent
   Portfolio Context (Redis) -> Strategist Agent
   Strategist Agent -> TradeProposal -> LangGraph state

4. RISK ASSESSMENT
   TradeProposal -> Risk Manager Agent
   Portfolio State (Redis/Postgres) -> Risk Manager Agent
   Risk Parameters (config) -> Risk Manager Agent
   Risk Manager Agent -> RiskDecision -> LangGraph state

5a. AUTO-EXECUTION (below threshold)
   RiskDecision (approved, small) -> Executor Agent
   Executor Agent -> ib_async -> IB Gateway -> Exchange
   Fill confirmation -> Portfolio State update
   Fill confirmation -> Redis event -> Dashboard + Alerts

5b. HUMAN APPROVAL (above threshold)
   RiskDecision (escalated) -> Redis event -> Dashboard (approval UI)
   Human approves/rejects via Dashboard
   If approved -> Executor Agent (same as 5a)
   If rejected -> Logged, pipeline ends
```

### Data Flow Contracts (Structured Messages Between Agents)

Each agent communicates via typed, structured messages -- not freeform text. This prevents the "telephone effect" identified in the TradingAgents research where information degrades across lengthy message chains.

```python
# Core data contracts (Pydantic models)

class ScanResult:
    symbol: str
    asset_type: Literal["equity", "etf", "futures"]
    setup_type: str               # e.g., "high_iv_mean_reversion"
    quant_signals: dict           # technical indicators, IV rank, etc.
    llm_reasoning: str            # narrative explanation
    confidence: float             # 0.0 - 1.0
    timestamp: datetime
    sources: list[str]            # data sources used

class TradeProposal:
    scan_result: ScanResult
    strategy_type: str            # e.g., "iron_condor", "vertical_spread"
    legs: list[OptionLeg]         # each leg: contract, action, quantity
    entry_criteria: dict          # limit prices, conditions
    max_loss: float
    target_profit: float
    estimated_greeks_impact: GreeksImpact
    llm_reasoning: str
    pricing_model_output: dict    # quant model results

class RiskDecision:
    proposal: TradeProposal
    decision: Literal["approved", "rejected", "modified", "escalated"]
    pre_trade_risk: PortfolioRisk
    projected_risk: PortfolioRisk
    rule_violations: list[str]    # any hard limit violations
    adjustments: list[str]        # modifications if decision == "modified"
    escalation_reason: str | None
    deterministic_pass: bool      # did it pass hard rules?
    llm_risk_assessment: str | None

class ExecutionResult:
    proposal: TradeProposal
    order_ids: list[int]
    fills: list[Fill]             # price, quantity, timestamp per leg
    total_commission: float
    slippage: float               # actual vs expected
    execution_time: float         # seconds from submission to fill
```

### Real-Time Data Flow (Concurrent with Pipeline)

```
IB Gateway -> ib_async -> Redis pub/sub:
  - channel: market.{symbol}.tick     (price updates)
  - channel: market.{symbol}.greeks   (Greeks updates)
  - channel: portfolio.positions      (position changes)
  - channel: portfolio.pnl            (P&L updates)
  - channel: orders.{orderId}.status  (order lifecycle)
  - channel: system.health            (connection status)
  - channel: alerts.{severity}        (alert events)

FastAPI WebSocket server subscribes to relevant Redis channels
  -> pushes to connected dashboard clients

Alert system subscribes to alerts.* channels
  -> routes to Slack/SMS based on severity
```

---

## Patterns to Follow

### Pattern 1: LLM + Quant Separation (Critical)

**What:** Strict boundary between what the LLM reasons about and what deterministic/quant code computes. LLMs handle research, synthesis, narrative reasoning, regime assessment. Quant code handles pricing, Greeks, signals, position sizing math.

**Why:** The Libertify framework research calls this out explicitly: "Strict separation between LLM reasoning and numerical computation." LLMs hallucinate numbers. They cannot reliably calculate Black-Scholes prices, implied volatilities, or Greeks. But they excel at synthesizing multiple information sources into a coherent thesis.

**Implementation:**
```python
# WRONG: Asking LLM to compute
prompt = "What is the delta of a 30-day ATM call with 25% IV?"

# RIGHT: LLM reasons, quant computes
llm_thesis = agent.reason("Given earnings in 5 days and IV rank at 85th
    percentile, what strategy type best captures IV mean reversion?")
# Returns: "Short iron condor -- IV is elevated and likely to contract post-earnings"

greeks = quantlib.compute_greeks(contract, spot, vol, rate, time)
price = quantlib.price_option(contract, model="black_scholes")
```

**Confidence:** HIGH -- verified across TradingAgents paper, Libertify framework, and multiple practitioner sources.

### Pattern 2: Deterministic Risk Gate Before LLM Risk Assessment

**What:** The Risk Manager runs hard deterministic rules first (position limits, Greeks limits, loss limits). Only proposals that pass all hard rules proceed to LLM-based risk reasoning.

**Why:** If the LLM is slow, hallucinating, or down, the system is still safe. Hard rules are the invariant. LLM assessment is additive intelligence, not a safety dependency.

**Implementation:**
```python
class RiskManager:
    def evaluate(self, proposal: TradeProposal, portfolio: PortfolioState) -> RiskDecision:
        # Stage 1: Deterministic rules (ALWAYS runs, FAST)
        violations = self.check_hard_limits(proposal, portfolio)
        if violations:
            return RiskDecision(decision="rejected", rule_violations=violations)

        # Stage 2: LLM assessment (OPTIONAL, adds intelligence)
        try:
            llm_assessment = await self.llm_risk_check(proposal, portfolio)
        except Exception:
            llm_assessment = None  # Degrade gracefully

        # Stage 3: Threshold check for human approval
        if proposal.max_loss > self.auto_execute_threshold:
            return RiskDecision(decision="escalated", ...)

        return RiskDecision(decision="approved", ...)
```

**Confidence:** HIGH -- this is a well-established pattern in financial systems. The project spec explicitly states "if risk manager is unreachable, no trades execute."

### Pattern 3: Event-Sourced Audit Trail

**What:** Every agent decision, every market data point that informed it, every risk check result -- all stored as immutable events in time-series order. Full reconstruction of "why did the system make this trade?"

**Why:** Options trading requires auditability. When a trade loses money, you need to trace back through: what did the scanner see, what was the strategist's reasoning, what risk checks passed, what were market conditions at execution time.

**Implementation:** Store events in PostgreSQL with TimescaleDB extension. Every agent writes its output as an immutable event with: agent_id, timestamp, event_type, input_hash, output_data, reasoning_text, market_context_snapshot.

**Confidence:** MEDIUM-HIGH -- pattern well-established in event sourcing literature; TimescaleDB for trading time-series data confirmed across multiple sources.

### Pattern 4: Paper/Live Toggle via Connection Configuration

**What:** The entire system code is identical for paper and live trading. The only difference is which IB Gateway port the system connects to: port 4002 for paper, port 4001 for live.

**Why:** IB Gateway itself handles the paper/live separation. This means no conditional logic in the codebase, no risk of paper-only code accidentally running live. Same pipeline, same risk checks, same everything -- just a different port.

**Implementation:**
```python
# config.yaml
trading:
  mode: "paper"  # or "live"
  ib_gateway:
    paper_port: 4002
    live_port: 4001
    host: "127.0.0.1"

# Connection logic
port = config.ib_gateway.paper_port if config.trading.mode == "paper" else config.ib_gateway.live_port
await ib.connectAsync(host, port, clientId=1)
```

**Confidence:** HIGH -- verified from IB official documentation. IB Gateway uses port 4002 for paper, 4001 for live.

### Pattern 5: Graceful Degradation with Circuit Breakers

**What:** The system has three circuit breaker levels:

1. **Agent-level**: If an individual agent (e.g., Scanner) fails repeatedly, it pauses and alerts. Other agents continue operating on existing positions.
2. **Pipeline-level**: If the Risk Manager or Executor fails, the entire new-trade pipeline halts. Position monitoring continues.
3. **System-level (Kill Switch)**: Emergency shutdown closes all new orders, optionally flattens positions, alerts via all channels.

**Why:** Trading systems must fail safely. A crash in the scanner should not cause the executor to go rogue. A crash in risk management must halt all trading.

**Implementation:**
```python
class CircuitBreaker:
    states = ["CLOSED", "OPEN", "HALF_OPEN"]

    def __init__(self, failure_threshold=3, recovery_timeout=300):
        self.state = "CLOSED"
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout  # seconds

    async def call(self, func, *args):
        if self.state == "OPEN":
            if time_since_opened > self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitOpenError("Agent circuit breaker is open")

        try:
            result = await func(*args)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise

class KillSwitch:
    """System-level emergency shutdown. Accessible from dashboard and alerts."""
    async def activate(self, flatten_positions: bool = False):
        # 1. Halt all agent pipelines
        await self.pipeline_manager.halt_all()
        # 2. Cancel all open orders
        await self.executor.cancel_all_orders()
        # 3. Optionally flatten positions
        if flatten_positions:
            await self.executor.flatten_all_positions()
        # 4. Alert on all channels
        await self.alert_system.emergency_alert("KILL SWITCH ACTIVATED")
```

**Confidence:** HIGH -- circuit breaker is a standard distributed systems pattern (Microsoft Azure Architecture Center documents it extensively). Kill switch is standard for algorithmic trading.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: LLM as Order Executor

**What:** Having the LLM directly generate order parameters (price, quantity, contract specifications) or directly call the IB API.

**Why bad:** LLMs hallucinate numbers. A hallucinated strike price or quantity could result in a real financial loss. LLMs also have non-deterministic output -- the same prompt might produce different order parameters.

**Instead:** LLM reasons about strategy selection and market thesis. Deterministic code constructs the actual order with validated parameters from the options chain. The LLM never touches order construction.

### Anti-Pattern 2: Shared Mutable State Between Agents

**What:** Agents directly modifying a shared dictionary or database row that other agents read concurrently.

**Why bad:** Race conditions. The Scanner updates a "current opportunity" field while the Strategist is reading it. The Risk Manager sees stale portfolio state because the Executor's fill update hasn't committed yet.

**Instead:** Use LangGraph's immutable state transitions. Each agent reads a state snapshot, produces a new state update. LangGraph handles the state transitions atomically. For real-time data (positions, prices), use Redis with pub/sub -- consumers get updates via events, not polling shared state.

### Anti-Pattern 3: Single IB Connection for Everything

**What:** Using one ib_async IB connection for market data, order execution, and account queries.

**Why bad:** IB's 50 messages/second limit applies per connection. Market data subscriptions, order submissions, and account queries all compete for the same message budget. A burst of market data requests can delay order submissions.

**Instead:** Use multiple IB client connections with different clientId values (IB supports up to 32 simultaneous API connections):
- clientId=1: Market data streaming
- clientId=2: Order execution
- clientId=3: Account/portfolio queries

This isolates concerns and prevents message contention.

**Confidence:** HIGH -- IB official docs confirm 50 msg/sec limit and multi-client support.

### Anti-Pattern 4: Polling the Dashboard for Updates

**What:** The React frontend polling a REST endpoint every N seconds for position updates, P&L changes, and agent status.

**Why bad:** Either too slow (missing real-time events) or too frequent (wasting resources). For a trading dashboard, stale data is dangerous.

**Instead:** WebSocket push from FastAPI. FastAPI subscribes to Redis channels, pushes events to connected WebSocket clients immediately. The frontend only uses REST for initial page load and user-initiated actions.

### Anti-Pattern 5: Treating Options Across Asset Classes Identically

**What:** Using the same contract handling logic for equity options, ETF options, and futures options.

**Why bad:** These have different:
- Contract multipliers (equity/ETF options = 100 shares, futures options vary by product)
- Margin requirements (portfolio margin vs Reg-T vs SPAN)
- Trading hours (equity options: 9:30-4:00 ET, futures options: nearly 24h for many products)
- Settlement types (AM vs PM settlement, cash vs physical delivery)
- Exercise styles (American vs European)

**Instead:** Model each asset class explicitly. Create an abstract `OptionsContract` base with asset-class-specific subclasses that encode their particular rules. The Risk Manager must understand these differences for accurate exposure calculation.

---

## Scalability Considerations

This is a single-user system, so "scale" means handling more instruments and more concurrent agent runs -- not more users.

| Concern | At 10 instruments | At 100 instruments | At 500+ instruments |
|---------|--------------------|--------------------|---------------------|
| Market data lines | Well within IB free tier (~100 lines) | May need additional IB data subscriptions | Requires tiered subscription; use snapshot requests for inactive symbols |
| Agent pipeline throughput | Single sequential run is fine | Need parallel pipeline instances per opportunity | Queue-based pipeline with worker pool |
| Database writes | Negligible | Moderate; TimescaleDB handles well | Batch inserts, compression policies |
| LLM API costs | Low (~$0.01-0.10 per scan cycle) | Moderate (~$1-10 per full scan) | Need model selection strategy: cheap models for filtering, expensive models for final decisions |
| Redis memory | Trivial | ~100MB for tick cache | May need eviction policies for old ticks |
| Dashboard WebSocket | 1 connection, no concern | Same | Same -- single user |

### IB-Specific Rate Limits to Architect Around

| Limit | Value | Architectural Response |
|-------|-------|----------------------|
| Outbound messages | 50/second/connection | Multiple connections with separate clientIds |
| Simultaneous market data lines | ~100 (varies by tier) | Subscription manager that rotates active subscriptions |
| Historical data requests | 6 identical in 2 sec; 60 in 10 min | Request queue with deduplication and pacing |
| Options chain requests | Throttled for ambiguous contracts | Use `reqSecDefOptParams` (unthrottled) over `reqContractDetails` |
| Max simultaneous API connections | 32 per account | More than sufficient; use 3-4 dedicated connections |

---

## Technology Decisions Summary

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Agent orchestration | LangGraph | Graph-based state management, async, human-in-the-loop, used by TradingAgents |
| IB connectivity | ib_async v2.1.0 | Asyncio-native, implements full IB protocol, replaces ib_insync, actively maintained |
| Message bus / cache | Redis (Streams + Pub/Sub) | In-memory speed for real-time data, pub/sub for event distribution, streams for reliable message delivery |
| Database | PostgreSQL + TimescaleDB | Relational for positions/orders/config, time-series for market data and audit trail |
| Options math | QuantLib or vollib | Industry-standard options pricing, Greeks computation, IV calculation |
| API server | FastAPI | Async-native, WebSocket support, high performance (15k RPS benchmarked), Pydantic integration |
| Frontend | React + TypeScript | Dominant ecosystem for dashboards, WebSocket support, component libraries for charts |
| LLM integration | LangChain (via LangGraph) | Multi-provider support (OpenAI, Anthropic, etc.), structured output, tool calling |
| Data validation | Pydantic | Type-safe data contracts between agents, JSON serialization, FastAPI integration |

---

## Suggested Build Order

The build order is dictated by dependency chains. Each component depends on components built before it.

### Phase 1: Foundation (No agents yet)

**Build:** IB connection layer, Market Data Service, Portfolio State Manager, Database schema

**Why first:** Every agent needs market data and portfolio context. Cannot test any agent without real (or paper) market data flowing. IB connection is the riskiest integration -- validate it early.

**Dependency:** Nothing. This is the foundation.

**Validates:** IB API connectivity, market data streaming, options chain retrieval, account state sync, paper trading toggle.

### Phase 2: Risk Engine (Deterministic only)

**Build:** Risk parameter configuration, deterministic rule engine (position limits, Greeks limits, loss limits, strategy restrictions), portfolio risk calculator

**Why second:** Risk is the hardest constraint in the system. Build it before any agent can propose trades. This ensures the safety net exists before any execution capability.

**Dependency:** Phase 1 (needs portfolio state and market data for Greeks calculations)

**Validates:** Risk rules enforce correctly, portfolio Greeks aggregate correctly across asset classes, loss limits trigger correctly.

### Phase 3: Execution Layer

**Build:** Executor Agent (order submission, lifecycle management, fill tracking), order state machine, paper trading validation

**Why third:** Before building the intelligent agents, build the mechanism to actually place orders. Test with manual trade proposals against the risk engine + executor. This validates the full "risk check -> execute -> track" path without needing AI.

**Dependency:** Phase 1 (IB connection), Phase 2 (risk gate)

**Validates:** Orders submit correctly, fills are tracked, portfolio state updates, paper/live toggle works, IB reconnection logic handles disconnects.

### Phase 4: Agent Pipeline (Intelligence)

**Build:** Scanner Agent, Strategist Agent, LangGraph orchestration, LLM integration, agent communication contracts

**Why fourth:** Now that data flows, risk enforces, and execution works, add the intelligence layer. If any agent produces bad output, the risk engine catches it. If execution fails, it is already battle-tested.

**Dependency:** Phase 1 (market data), Phase 2 (risk gate), Phase 3 (execution)

**Validates:** Scanner finds real opportunities, Strategist constructs valid strategies, pipeline flows end-to-end through paper trading, LLM + quant separation works correctly.

### Phase 5: Dashboard + Alerts

**Build:** FastAPI API server, React dashboard, WebSocket real-time push, alert system (Slack/SMS), human approval flow

**Why fifth:** The system can operate headless (auto-executing small trades, alerting via logs). The dashboard adds visibility and human control. Building it after the pipeline works means you have real data to display and real flows to visualize.

**Dependency:** Phase 1-4 (needs running system to display)

**Validates:** Real-time data pushes to dashboard, approval flow works end-to-end, alerts fire correctly, kill switch functions.

### Phase 6: Hardening + Advanced Features

**Build:** Circuit breakers, advanced risk (correlation, regime-aware), LLM risk assessment layer, performance monitoring, multi-asset options handling (equity vs ETF vs futures differences)

**Why last:** Polish and production-readiness. The system works end-to-end; this phase makes it robust.

**Dependency:** All previous phases

**Validates:** System recovers from failures, handles edge cases (IB disconnects, LLM timeouts, partial fills), futures options handled differently from equity options.

```
Build Dependency Graph:

Phase 1: Foundation ─────────────────────────────────────┐
    │                                                     |
    v                                                     |
Phase 2: Risk Engine ──────────────────────────────┐      |
    │                                               |     |
    v                                               |     |
Phase 3: Execution ────────────────────────────┐    |     |
    │                                           |   |     |
    v                                           v   v     v
Phase 4: Agent Pipeline ──────> Phase 5: Dashboard + Alerts
    │                                           |
    v                                           v
Phase 6: Hardening ─────────────────────────────┘
```

---

## Key Architectural Decisions to Lock In Early

| Decision | Recommendation | Consequence of Getting Wrong |
|----------|---------------|----------------------------|
| Agent communication format | Pydantic models (typed, validated, serializable) | Untyped dicts between agents leads to runtime errors and debugging nightmares |
| State management | LangGraph immutable state + Redis for real-time | Wrong choice here means rewriting the entire agent coordination layer |
| IB connection strategy | Multiple clientIds (data, orders, account) | Single connection causes message contention under load |
| Risk engine architecture | Deterministic rules first, LLM second | If LLM is in the critical path for risk, a slow/failed LLM means unsafe trades |
| Database for time-series | TimescaleDB (PostgreSQL extension) | Separate time-series DB means operational complexity; vanilla Postgres struggles at scale |
| Paper/live toggle | IB Gateway port switching only | Conditional logic in codebase is a safety hazard |

---

## Sources

### HIGH Confidence (Official / Authoritative)
- [Interactive Brokers TWS API Documentation](https://interactivebrokers.github.io/tws-api/introduction.html) -- API architecture, message limits, options handling
- [IB API Options](https://interactivebrokers.github.io/tws-api/options.html) -- Options chain retrieval, contract specs
- [IB API Option Greeks](https://interactivebrokers.github.io/tws-api/option_computations.html) -- Real-time Greeks streaming, tick types
- [ib_async GitHub](https://github.com/ib-api-reloaded/ib_async) -- v2.1.0, asyncio-native IB wrapper, replaces ib_insync
- [LangGraph Official](https://www.langchain.com/langgraph) -- Agent orchestration framework, state management
- [Google Multi-Agent Design Patterns (InfoQ, Jan 2026)](https://www.infoq.com/news/2026/01/multi-agent-design-patterns/) -- Eight essential patterns including sequential pipeline, human-in-the-loop

### MEDIUM Confidence (Multiple Sources Agree)
- [TradingAgents: Multi-Agent LLM Financial Trading Framework (arXiv)](https://arxiv.org/html/2412.20138v3) -- Reference architecture for multi-agent trading, LangGraph usage, analyst/researcher/trader/risk roles
- [TradingAgents GitHub](https://github.com/TauricResearch/TradingAgents) -- Open-source implementation of multi-agent trading
- [Libertify Financial Agents Orchestration Framework](https://www.libertify.com/interactive-library/financial-agents-orchestration-framework-agentic-trading/) -- Nine-agent architecture, MCP+A2A communication, five binary risk gates, memory agent pattern
- [Microsoft Azure Circuit Breaker Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker) -- Standard circuit breaker implementation
- [TimescaleDB for Algorithmic Trading](https://siddharthqs.com/introduction-to-timescaledb-for-algorithmic-trading) -- Time-series DB for trading data

### LOW Confidence (Single Source / Unverified)
- Performance benchmark claim of FastAPI at 15,000 RPS (single Medium article)
- Redis Streams specific integration pattern with LangGraph (architectural inference, not documented together)
- Specific IB market data line limits (~100) -- varies by subscription tier and is not precisely documented in API docs
