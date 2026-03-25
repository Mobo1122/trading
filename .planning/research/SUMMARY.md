# Project Research Summary

**Project:** AI-Powered Multi-Agent Options Trading System
**Domain:** Algorithmic options trading with Interactive Brokers via multi-agent LLM pipeline
**Researched:** 2026-03-25
**Confidence:** HIGH

## Executive Summary

This is a safety-critical financial automation system that combines multi-agent LLM orchestration with quantitative options analytics and Interactive Brokers execution. Experts build systems like this by strictly separating concerns across three layers: a deliberative agent pipeline (scan, strategize, risk-check, execute) orchestrated by a state machine; a real-time event bus for market data and dashboard updates; and a deterministic risk gate that enforces hard constraints independently of the AI layer. The TradingAgents framework (the leading academic reference implementation) and production systems like Libertify both validate this tri-layer pattern. The key architectural insight is that LLMs and quant code are not interchangeable — LLMs handle research synthesis, regime reasoning, and natural language explanation; deterministic Python handles all pricing, Greeks, position sizing, and order parameters.

The recommended approach is to build safety infrastructure first and intelligence last. The stack centers on Python 3.12 + ib_async 2.1.0 for IB connectivity, PydanticAI 1.71 for per-agent definition, LangGraph 1.1.3 for pipeline orchestration, FastAPI for the API/WebSocket server, PostgreSQL + TimescaleDB for all persistence, and Redis for real-time pub/sub and caching. The frontend is Next.js 16 with lightweight-charts for financial visualization. All versions verified on PyPI/npm as of 2026-03-25. The dual-framework AI approach (PydanticAI per-agent, LangGraph for orchestration) is the critical stack decision: each individual agent is a typed PydanticAI agent with structured outputs; LangGraph connects them in a directed graph with state persistence and human-in-the-loop interrupt support.

The dominant risks are not technical but sequencing-related. Every catastrophic automated trading failure — Knight Capital's $440M loss, individual account blow-ups — resulted from building the intelligence layer before the safety layer. LLM hallucination in a multi-agent pipeline can amplify errors up to 17x (Google DeepMind, Dec 2025). The mandatory mitigation is: kill switch and risk gate before any agent can place orders; deterministic validation of every LLM output before it reaches execution; state reconciliation after every IB reconnection. The system must be able to operate safely even if every LLM agent is down or hallucinating.

## Key Findings

### Recommended Stack

See full details in `.planning/research/STACK.md`.

The stack was chosen around five guiding principles: Python-first (the IB/quant/AI ecosystem demands it), async-native (all I/O is asyncio-based), separation of concerns (agent layer, execution layer, and dashboard are distinct services), paper-first (paper/live is a config toggle, not a code branch), and minimal framework lock-in (swap LLM provider or charting library without rewrites).

**Core technologies:**
- **ib_async 2.1.0** — IB TWS/Gateway connectivity — the maintained asyncio successor to ib_insync (original author died in 2024); implements the IB binary protocol directly; use IB Gateway (not TWS) for headless production operation
- **PydanticAI 1.71 + LangGraph 1.1.3** — agent framework + orchestration — PydanticAI defines each agent with typed tool calls and structured outputs; LangGraph manages the workflow graph with state persistence, retries, and human-in-the-loop interrupts; do NOT conflate them
- **py_vollib + py_vollib_vectorized** — options pricing and vectorized Greeks — mathematically stable (Black-Scholes doesn't change); WARNING: last PyPI release 2017/2021, Python 3.12 compatibility needs hands-on verification
- **FastAPI 0.135.2 + uvicorn 0.42.0** — async REST API and WebSocket server — native async, Pydantic-integrated, handles both REST for initial load and WebSocket push for real-time updates
- **PostgreSQL 16 + TimescaleDB** — single-database strategy combining relational (positions, orders, config) with time-series (OHLCV, Greeks snapshots, audit trail) via a single connection pool and migration toolchain
- **Redis 7.4.0** — real-time cache + pub/sub + streams — three roles in one: position/Greeks cache, event bus between services, durable message log
- **Next.js 16.2.1 + lightweight-charts** — web dashboard — App Router, server components for initial load, lightweight-charts (Apache 2.0, from TradingView team) for financial charting; Zustand for WebSocket state
- **uv** — Python package management — 10-100x faster than pip, strict lock files, the 2025-2026 standard

**Notable rejections:** ib_insync (unmaintained), Flask/Django/Streamlit (sync or wrong abstraction), QuestDB standalone (operational complexity > benefit at this scale), Kafka/RabbitMQ (over-engineered for single-user system), CrewAI (hides control flow needed for financial safety), QuantLib (exotic derivatives overkill for listed options).

### Expected Features

See full details in `.planning/research/FEATURES.md`.

**Must have (table stakes):**
- IB TWS/Gateway connection with auto-reconnect and daily restart handling
- Multi-leg combo/spread order placement and state tracking
- Paper trading mode (same code, different port)
- Option chain retrieval with Greeks and IV streaming
- Portfolio-level Greeks aggregation (delta, gamma, theta, vega) in real-time
- Daily loss limits / circuit breakers that persist across agent restarts
- Strategy restrictions (no naked options as a hard rule)
- Risk manager fail-safe: if the risk agent is unreachable, ALL new trades halt
- Positions display with real-time P&L
- Agent decision/reasoning display (auditable, not a black box)
- Trade execution alerts (Slack/SMS) and risk event alerts
- Configurable auto-execute threshold with approval workflow for large trades

**Should have (differentiators):**
- IV rank/percentile analysis driving strategy selection
- Market regime detection (bull/bear/sideways/volatile) for adaptive strategy mix
- Earnings event awareness (IV expansion pre-earnings, crush post-earnings)
- Automated position rolling for approaching expirations
- Portfolio P&L scenario analysis (what-if: underlying +/- X%, IV +/- Y%)
- Interactive Slack approval (approve/reject without opening dashboard)
- Strategy performance attribution by agent, strategy type, regime

**Defer to post-MVP:**
- Backtesting engine — explicitly out of scope; paper trading is v1 validation
- Volatility surface / skew analysis — advanced, costly data, not blocking
- Unusual options activity detection — requires external data (CBOE/OPRA feeds)
- Correlation awareness across positions
- Dynamic hedge suggestions
- Market regime detection (ML complexity; can enhance scanner in v2)

**Feature dependency chain:** IB API connection -> market data -> Greeks -> risk manager -> executor. The agent pipeline dependency is strictly: scanner -> strategist -> risk manager -> executor. Nothing can short-circuit this chain.

### Architecture Approach

See full details in `.planning/research/ARCHITECTURE.md`.

The architecture is a composite multi-agent pipeline: Google's Sequential Pipeline pattern for the core trading flow (scan -> strategize -> risk check -> execute), Parallel Fan-Out inside the scanner for concurrent sub-scans, and Human-in-the-Loop via LangGraph interrupt/resume for trade approval. Five architectural layers: Data Ingestion (IB + external), Agent Orchestration (LangGraph), Risk Gate (deterministic rules first, LLM second), Execution (ib_async), and Presentation (FastAPI + React). IB connections use multiple clientIds to avoid 50 msg/sec contention: one for market data streaming, one for order execution, one for account/portfolio queries.

**Major components:**
1. **Market Data Service** — ib_async + Redis pub/sub; IB subscription management (100-line limit); publishes tick events to Redis channels; everything depends on this
2. **Scanner Agent** — LangGraph node; parallel sub-scans (technical, fundamental, sentiment); produces typed `ScanResult` with quant signals + LLM reasoning narrative
3. **Strategist Agent** — LangGraph node; LLM selects strategy type; quant code selects strikes/pricing; produces typed `TradeProposal` with Greeks impact
4. **Risk Manager Agent** — two-tier: deterministic hard rules first (always runs), LLM risk assessment second (optional, degrades gracefully); produces `RiskDecision` (approved / rejected / modified / escalated)
5. **Executor Agent** — LangGraph node; state machine (PENDING -> SUBMITTED -> PARTIAL_FILL -> FILLED / CANCELLED / ERROR); implements auto-execute vs. approval routing
6. **Portfolio State Manager** — dual-write pattern: IB is authoritative, local DB is working copy; reconciles on every reconnect and periodically during market hours
7. **Web Dashboard + API Server** — FastAPI WebSocket subscribed to Redis channels; dashboard is a consumer only; write paths are limited to approve/reject, risk param changes, kill switch
8. **Alert System** — Slack webhooks + Twilio SMS; consumes Redis `alerts.*` channel; routes by severity

**Patterns to lock in early:** LLM + quant strict separation (LLM never touches order construction or Greek calculations); deterministic risk gate before LLM risk assessment; event-sourced immutable audit trail in TimescaleDB; paper/live as IB Gateway port toggle only (no conditional logic in codebase); circuit breakers at agent, pipeline, and system (kill switch) levels.

### Critical Pitfalls

See full details in `.planning/research/PITFALLS.md`.

1. **No kill switch / runaway order protection** — Knight Capital lost $440M in 45 minutes. Build the kill switch and per-second order rate cap BEFORE the first order is ever placed. Also implement a dead man's switch: if the risk manager stops responding, halt all new orders. Phase 1, non-negotiable.

2. **LLM hallucination in financial decisions** — The TradeTrap paper (arXiv:2512.02261) documented "epistemic hallucination" where agents believe they hold positions they already liquidated. Prevention: LLM never generates order parameters or calculates numbers; a deterministic "reality check" layer validates all LLM factual claims against actual market data and portfolio state before anything reaches the executor. Design this into Phase 1 architecture.

3. **Multi-agent error cascade (17x amplification)** — Google DeepMind Dec 2025 research found unstructured agent networks amplify errors up to 17.2x; coordination failures account for 36.94% of multi-agent system failures. Prevention: centralized LangGraph orchestrator (not a mesh), schema-validated Pydantic contracts between every agent pair, checkpoint validation after each node, circuit breakers that halt the pipeline on validation failure.

4. **IB connection instability causing orphaned orders** — IB Gateway restarts daily (~11:45 PM - 12:45 AM ET). State reconciliation routine must run on every reconnection, every 5 minutes during market hours, and before/after market open/close. Use `reqOpenOrders()` and `reqPositions()` as source of truth, not local tracking. Multiple clientIds (data, orders, account) to isolate message budgets.

5. **Options-specific expiration risks** — Early assignment on short calls before ex-dividend dates, pin risk at expiration, after-hours exercise (options stop at 4 PM but stocks trade until 8 PM; OCC auto-exercises $0.01+ ITM). Hard rules: auto-close or roll positions with < 7 DTE; block short calls within 5 days of ex-dividend; close all positions within $0.50 of strike by 3 PM ET on expiration day; morning reconciliation handler to detect overnight assignments.

6. **Paper trading false confidence** — IB's paper simulator does not support penny increments, fills from deep book, or realistic combo order fills. Options slippage can be 5-20% in illiquid strikes. Treat paper trading as integration test (verifies plumbing works), NOT profitability test. Build explicit slippage models and start live trading at 10% of target size.

## Implications for Roadmap

Based on combined research from all four files, the phase structure is dictated by a hard dependency chain. Safety and data infrastructure must precede intelligence. The research unanimously agrees on this sequencing — the FEATURES.md MVP recommendation, ARCHITECTURE.md build order, and PITFALLS.md meta-pitfall warning all converge on the same order.

### Phase 1: Safety + Data Foundation

**Rationale:** Nothing else can safely exist without this. The kill switch, IB connection layer, market data streaming, and state reconciliation are prerequisites for every other component. Building agents before this layer is the #1 cause of catastrophic trading system failures (Knight Capital pattern).

**Delivers:** IB Gateway connection with auto-reconnect and state reconciliation; market data streaming (quotes, Greeks, IV, options chains); portfolio state manager with dual-write reconciliation; kill switch and hard order rate limits; kill switch accessible before any agent is built; database schema (PostgreSQL + TimescaleDB) and Redis pub/sub channels; paper/live port toggle.

**Addresses (from FEATURES.md):** IB connection + auto-reconnect, market data streaming, option chain retrieval, paper trading mode, system health indicators.

**Avoids (from PITFALLS.md):** Pitfall 1 (kill switch), Pitfall 6 (IB connection instability), Pitfall 8 (API rate limits), Pitfall 12 (contract specification errors).

**Research flag:** NEEDS deeper research — IB Gateway Docker image stability (community image, not official), py_vollib Python 3.12 compatibility (last release 2017), IB market data subscription requirements and costs.

### Phase 2: Risk Engine (Deterministic Only)

**Rationale:** Risk must exist and be proven before any trade can be proposed or executed. Build the entire deterministic risk layer — position limits, Greeks limits, loss circuit breakers, strategy restrictions, margin monitoring — while there is still no intelligence layer that could circumvent it. LLM risk assessment is deliberately excluded from this phase.

**Delivers:** Rule-based risk engine with hard limits (position sizing, portfolio Greeks exposure, daily/weekly loss limits, no-naked-options rule); circuit breaker that halts all trading if risk manager is unreachable; pre-trade margin check via IB `whatIfOrder()`; margin utilization monitoring (alert at 60%, halt at 70%, reduce at 80%); options-specific rules (expiration calendar, ex-dividend detection, DTE flags).

**Addresses (from FEATURES.md):** Position sizing limits, Greeks exposure limits, daily loss limits, strategy restrictions, risk manager fail-safe.

**Avoids (from PITFALLS.md):** Pitfall 5 (options expiration risks), Pitfall 10 (margin surprises), Pitfall 1 (risk gate as hard prerequisite to execution).

**Research flag:** Standard patterns — deterministic rule engines and circuit breakers are well-documented. Skip dedicated research phase.

### Phase 3: Execution Layer

**Rationale:** Validate the full "risk check -> execute -> track -> reconcile" path without any AI. Manual trade proposals flow through risk engine to executor, validate paper fills, confirm IB reconnection handling, and stress-test the order state machine. This establishes that the execution layer is bulletproof before agents can send proposals to it.

**Delivers:** Executor agent with order state machine (PENDING -> SUBMITTED -> PARTIAL_FILL -> FILLED / CANCELLED / ERROR); multi-leg combo/spread order support; fill tracking and slippage measurement vs expected; IB reconnection recovery (resubmit lost orders, reconcile fills missed during disconnect); auto-execute vs. approval routing skeleton; alert system (Slack/SMS) for order events.

**Addresses (from FEATURES.md):** Order placement and state tracking, multi-leg combo orders, paper trading validation, trade execution alerts.

**Avoids (from PITFALLS.md):** Pitfall 6 (orphaned orders from IB disconnect), Pitfall 4 (paper trading limitations — slippage models built here).

**Research flag:** Standard patterns — IB order management is well-documented. Skip research phase. IB-specific quirks (clientId management, daily restart window) are covered in STACK.md and PITFALLS.md.

### Phase 4: Agent Pipeline (Intelligence Layer)

**Rationale:** Now that data flows, risk enforces, and execution is tested, the intelligence layer is safe to add. Bad agent output gets caught by the schema validation and risk gate. Bad execution is already battle-tested. The LangGraph pipeline wires together scanner, strategist, risk manager (LLM tier added), and executor with Pydantic-validated contracts between every node.

**Delivers:** Scanner agent (parallel sub-scans: technical signals + LLM market research + IV rank analysis); strategist agent (LLM selects strategy type, quant code selects strikes); risk manager LLM tier (regime assessment layered on top of Phase 2 deterministic rules); LangGraph orchestration of full pipeline with state persistence and retries; agent reasoning chain logging (full LLM prompt + completion stored per trade); structured data contracts (ScanResult, TradeProposal, RiskDecision, ExecutionResult).

**Addresses (from FEATURES.md):** Scanner agent, strategist agent, risk manager agent, executor agent, agent reasoning display, IV rank/percentile analysis, earnings event awareness.

**Avoids (from PITFALLS.md):** Pitfall 2 (LLM hallucination — reality check layer validates all LLM claims), Pitfall 3 (error cascade — schema-validated contracts + checkpoint validation), Pitfall 13 (over-engineering — start with 4 agents, no more).

**Research flag:** NEEDS deeper research — LangGraph + PydanticAI integration pattern (per-agent PydanticAI as LangGraph node) is not widely documented as a combined pattern; needs prototyping. Also: Claude vs GPT-4o routing strategy for cost/latency optimization per agent.

### Phase 5: Dashboard + Human-in-the-Loop

**Rationale:** The system runs headless at this point, placing small trades autonomously and logging decisions. Adding the dashboard gives visibility into live state and enables the human approval flow for large trades. Build this after the pipeline is working so the dashboard has real data to display.

**Delivers:** Next.js dashboard with WebSocket real-time push (positions, P&L, portfolio Greeks, agent reasoning); FastAPI WebSocket server subscribing to Redis channels; human approval UI for escalated trades (trade context, Greeks impact, max loss scenario, timeout); kill switch in dashboard UI; lightweight-charts candlestick display; Slack interactive approval (approve/reject buttons without opening dashboard); system health indicators.

**Addresses (from FEATURES.md):** Positions display, portfolio Greeks display, trade history log, agent reasoning display, hybrid autonomy (auto-execute threshold + approval workflow), alerts.

**Avoids (from PITFALLS.md):** Pitfall 15 (human approval UX — designed with context, tiered thresholds, and timeout-to-reject), Pitfall 11 (inadequate audit trail — full decision chain accessible from dashboard).

**Research flag:** Standard patterns for FastAPI WebSocket + React. Skip research phase. lightweight-charts integration is well-documented.

### Phase 6: Hardening + Advanced Features

**Rationale:** System is end-to-end functional. This phase makes it robust to failure modes and adds the differentiating features. Circuit breakers, LLM agent-level graceful degradation, multi-asset class handling (equity vs ETF vs futures options differences), and performance monitoring.

**Delivers:** Agent-level circuit breakers (scanner failure doesn't stop position monitoring); pipeline-level circuit breakers; advanced risk (correlation awareness, portfolio P&L scenarios); multi-asset options handling (futures options have different multipliers, margin, trading hours, settlement); strategy performance attribution; Prometheus metrics and structured logging (structlog with bound context for trade traceability); operational runbook for daily restart window.

**Addresses (from FEATURES.md):** Portfolio P&L scenario analysis, multi-asset options awareness, strategy performance attribution, correlation awareness.

**Avoids (from PITFALLS.md):** Pitfall 5 (futures options vs equity options differences), Pitfall 7 (overfitting — walk-forward strategy validation), Pitfall 9 (stale volatility data — freshness checks and spread-width filters).

**Research flag:** NEEDS research on futures options specifics (ES, NQ contract specs, SPAN margin) — different from equity options in ways that require explicit handling.

### Phase Ordering Rationale

- **Safety before intelligence** is the single most important ordering decision. The PITFALLS.md meta-pitfall explicitly calls this out: "every catastrophic failure in automated trading history came from insufficient safety infrastructure, not insufficient intelligence."
- **Execution before agents** means agents inherit a battle-tested execution layer. Agents can propose bad trades; only the execution layer actually touches the broker.
- **Dashboard after pipeline** means the UI has real data from day one and the approval flow can be end-to-end tested with actual agent outputs.
- **Phases 1-3 are the boring but non-negotiable foundation.** The system cannot do anything interesting during these phases. That is correct and expected.

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 1:** IB Gateway Docker image stability (community-maintained, not official IB); py_vollib Python 3.12 compatibility; exact IB market data subscription packages and monthly costs. Recommend hands-on prototyping sprint before committing the Phase 1 architecture.
- **Phase 4:** LangGraph + PydanticAI combined integration pattern — prototype the "PydanticAI agent as LangGraph node" pattern before building the full pipeline. LangGraph 1.0 shipped Oct 2025; integration examples with PydanticAI are sparse.
- **Phase 6:** Futures options specifics (ES, NQ, /CL multipliers; SPAN margin vs Reg-T; settlement differences; extended trading hours). Requires IB-specific research.

**Phases with standard patterns (skip research phase):**
- **Phase 2:** Deterministic risk rule engines and circuit breakers are well-documented patterns.
- **Phase 3:** IB order management (multi-leg orders, state tracking) is covered in STACK.md and IB official docs.
- **Phase 5:** FastAPI WebSocket + React dashboard integration is mature and well-documented.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified on PyPI/npm 2026-03-25. Exception: py_vollib Python 3.12 compat needs hands-on test; LangGraph+PydanticAI combined pattern is architecturally sound but not widely documented together. |
| Features | HIGH | IB API capabilities confirmed from official docs. Options trading table stakes are industry-established. AI agent features rated MEDIUM for novelty. |
| Architecture | MEDIUM-HIGH | Pipeline pattern validated by TradingAgents framework (academic + open-source). Redis Streams + LangGraph specific integration is an architectural inference, not documented together. Multiple clientId IB strategy confirmed by IB docs. |
| Pitfalls | HIGH | Critical pitfalls sourced from IB official docs, academic research (TradeTrap, DeepMind multi-agent paper), and documented industry failures (Knight Capital). Minor pitfalls based on practitioner consensus. |

**Overall confidence:** HIGH

### Gaps to Address

- **py_vollib Python 3.12 compatibility** — last PyPI release was 2017. Before committing to py_vollib in Phase 1, run a quick compatibility test. If it fails, implement Black-Scholes analytically (straightforward math) or use `blackscholes` package as fallback. Do not block Phase 1 on this; validate in a spike.

- **IB Gateway Docker image** — the community image `ghcr.io/gnzsnz/ib-gateway` is not official IB software. Validate its stability and update cadence before production reliance. Alternative: run IB Gateway + IBC directly on the host.

- **LangGraph + PydanticAI integration pattern** — the exact mechanism for using a PydanticAI agent as a LangGraph node needs a working prototype before Phase 4 planning. Allocate a 1-2 day spike in Phase 4 planning.

- **IB data subscription costs** — budget $30-100/month minimum for real-time US options data. Audit the exact subscription bundle needed (US Securities Snapshot + Futures Value Bundle, US Equity and Options Add-On Streaming Bundle) before Phase 1 development to avoid surprises.

- **WebSocket scaling** — FastAPI handling both WebSocket connections to dashboard clients and the trading engine's market data processing in a single process. Likely needs separate processes (trading engine vs API server). Validate in Phase 5 planning.

## Sources

### Primary (HIGH confidence — verified PyPI/npm/official docs)
- [ib_async on PyPI](https://pypi.org/project/ib_async/) — v2.1.0, asyncio IB client
- [LangGraph on PyPI](https://pypi.org/project/langgraph/) — v1.1.3, orchestration
- [PydanticAI on PyPI](https://pypi.org/project/pydantic-ai/) — v1.71.0, agent framework
- [FastAPI on PyPI](https://pypi.org/project/fastapi/) — v0.135.2
- [IBKR TWS API Documentation](https://interactivebrokers.github.io/tws-api/) — API limits, options, order types
- [IB TWS API Order Limitations](https://interactivebrokers.github.io/tws-api/order_limitations.html) — 50 msg/sec, pacing rules
- [IB Paper Trading vs Live Trading](https://www.interactivebrokers.com/campus/trading-lessons/paper-trading-vs-live-trading-whats-the-difference/) — simulator limitations
- [IB Exercise and Assignment](https://www.interactivebrokers.com/campus/trading-lessons/exercise-and-assignment/) — assignment mechanics
- [Google Multi-Agent Design Patterns (InfoQ, Jan 2026)](https://www.infoq.com/news/2026/01/multi-agent-design-patterns/) — sequential pipeline pattern

### Secondary (MEDIUM confidence — multiple sources agree)
- [TradingAgents: Multi-Agent LLM Financial Trading Framework (arXiv)](https://arxiv.org/html/2412.20138v3) — reference multi-agent trading architecture
- [TradeTrap paper (arXiv:2512.02261)](https://arxiv.org/html/2512.02261v1) — LLM hallucination in trading agents
- [Why Do Multi-Agent LLM Systems Fail? (arXiv:2503.13657)](https://arxiv.org/html/2503.13657v1) — 17x error amplification finding
- [Libertify Financial Agents Orchestration Framework](https://www.libertify.com/interactive-library/financial-agents-orchestration-framework-agentic-trading/) — nine-agent architecture, five binary risk gates
- [TimescaleDB for Algorithmic Trading](https://siddharthqs.com/introduction-to-timescaledb-for-algorithmic-trading) — time-series trading data patterns
- [Knight Capital Case Study](https://www.henricodolfing.ch/en/case-study-4-the-440-million-software-error-at-knight-capital/) — $440M loss from runaway algorithm

### Tertiary (LOW confidence — single source or inference, needs validation)
- IB Gateway community Docker image stability — not official IB; quality unknown
- py_vollib Python 3.12 compatibility — needs hands-on test; last release 2017
- LangGraph + PydanticAI combined integration pattern — architecturally sound but sparse documentation as a combined pattern
- LangGraph overhead benchmarks — third-party, not official measurements

---
*Research completed: 2026-03-25*
*Ready for roadmap: yes*
