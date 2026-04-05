# Options Trading AI Agents

## What This Is

A multi-agent AI system that autonomously trades options across US equities, ETFs, and futures using the Interactive Brokers API. A LangGraph-orchestrated pipeline of specialized agents — scanner, strategist, risk manager, executor — collaborates to find alpha, construct options strategies, and execute trades within user-defined risk constraints. A deterministic risk engine enforces position limits, Greeks exposure caps, and loss circuit breakers as a non-bypassable gate. Small trades auto-execute; larger ones require human approval via Slack or web dashboard. A Next.js dashboard and real-time alerts provide full visibility into agent decisions, positions, and P&L.

## Core Value

The agents find and execute profitable options trades autonomously while never violating the user's risk constraints — the risk management layer is the hardest constraint in the system.

## Requirements

### Validated

- Multi-agent pipeline: scanner → strategist → risk manager → executor — v1
- LLM + quantitative hybrid reasoning (LLMs for research/synthesis, quant models for signals/pricing) — v1
- Interactive Brokers API integration (TWS/Gateway) for order execution and market data — v1
- Multi-asset options trading: US equities, ETFs, and futures options — v1
- Risk management layer: position sizing limits, Greeks exposure limits (delta/theta/vega), daily/weekly loss limits, strategy restrictions (e.g., no naked options) — v1
- Hybrid autonomy: auto-execute trades below configurable threshold, require approval above it — v1
- Web dashboard: positions, P&L, agent reasoning/decisions, trade history — v1
- Real-time alerts via Slack/SMS for trades and risk events — v1
- Paper trading toggle: switch between live and paper accounts for strategy validation — v1
- Portfolio-level risk monitoring and reporting — v1
- Market regime detection adapts strategy mix to current conditions — v1
- Automatic position rolling for expiring positions — v1
- P&L scenario analysis (what-if: underlying +/- X%, IV +/- Y%, T+N days) — v1
- Slack interactive approve/reject buttons for trade approval — v1
- Approval timeout defaults to reject (safe default) — v1

### Active

(None yet — define for next milestone)

### Out of Scope

- Crypto or forex options — IB equities/ETFs/futures only; different exchanges and data sources
- Mobile native app — web dashboard + Slack covers mobile needs; massive engineering surface
- Social/copy trading features — single-user system; multi-tenancy adds auth, compliance, and community complexity
- Backtesting engine — deferred to v2
- Custom brokerage integrations — IB only
- Custom options pricing models — IB Greeks + scipy Black-Scholes sufficient
- HFT/sub-second latency — options bid-ask spreads are wide; IB has 50 msg/sec limit; focus on decision quality

## Context

- User is an active Interactive Brokers account holder, familiar with options trading but hasn't coded against the IB API before
- IB Gateway used via ib_async library (async Python wrapper for TWS API)
- v1 shipped: 26,781 LOC (23,628 Python + 3,153 TypeScript), 388 tests, 10 phases, 45 plans
- Tech stack: Python 3.12, ib_async, PydanticAI, LangGraph, FastAPI, Next.js, PostgreSQL/TimescaleDB, Redis
- Runtime validation against live IB Gateway and Docker infrastructure is the next step before paper trading

## Constraints

- **Brokerage**: Interactive Brokers only — all trading, market data, and account management through IB APIs
- **Regulation**: Must respect IB's order rate limits and API usage policies
- **Risk**: Risk management layer must be fail-safe — if risk manager is unreachable, no trades execute
- **Latency**: Options trading doesn't require HFT-level latency, but order execution should be responsive (seconds, not minutes)
- **Cost**: LLM API calls add per-trade cost — agent reasoning should be efficient and avoid unnecessary token usage

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LLM + Quant hybrid over pure LLM | LLMs good at research/synthesis but unreliable for precise pricing; quant models better for signals | Good — PydanticAI agents handle research, scipy/IB handle pricing |
| Full agent pipeline over single-agent | Separation of concerns — each agent has clear responsibility, easier to debug and improve | Good — clean node boundaries in LangGraph |
| Hybrid autonomy over full auto | Balances speed for small trades with human oversight for larger risk | Good — three-way routing works well |
| Paper trading toggle over separate system | Same codebase, same pipeline — just switches IB account type | Good — TRADING_MODE env var, zero code changes |
| Safety before intelligence (phase ordering) | Phases 1-4 build foundation before AI agents — ensures system can operate safely even if all agents fail | Good — risk gate tested independently of agents |
| Deterministic risk gate before LLM assessment | Phase 3 pure rules, LLM tier in Phase 5 — ensures risk enforcement is auditable and predictable | Good — no LLM can override deterministic limits |
| PydanticAI + LangGraph for agents | Clean dependency injection, typed outputs, checkpoint persistence | Good — sparse docs concern resolved during implementation |
| Deterministic regime detection (not ML) | Testability and auditability critical for real-money system | Good — hysteresis prevents whiplash |
| Property setter injection for cross-component wiring | Breaks circular dependencies during construction (e.g., FillTracker.circuit_breaker) | Good — consistent pattern across phases |
| Closure-based pipeline routing | Three-way approval gate needs deps access for threshold checking | Good — clean separation of routing logic |

---
*Last updated: 2026-04-05 after v1 milestone*
