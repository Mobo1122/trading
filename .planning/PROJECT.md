# Options Trading AI Agents

## What This Is

A multi-agent AI system that autonomously trades options across US equities, ETFs, and futures using the Interactive Brokers API. A pipeline of specialized agents — scanner, strategist, risk manager, executor — collaborates to find alpha, construct options strategies, and execute trades within user-defined risk constraints. Small trades auto-execute; larger ones require human approval. A web dashboard and real-time alerts provide full visibility into agent decisions, positions, and P&L.

## Core Value

The agents find and execute profitable options trades autonomously while never violating the user's risk constraints — the risk management layer is the hardest constraint in the system.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Multi-agent pipeline: scanner → strategist → risk manager → executor
- [ ] LLM + quantitative hybrid reasoning (LLMs for research/synthesis, quant models for signals/pricing)
- [ ] Interactive Brokers API integration (TWS/Gateway) for order execution and market data
- [ ] Multi-asset options trading: US equities, ETFs, and futures options
- [ ] Risk management layer: position sizing limits, Greeks exposure limits (delta/theta/vega), daily/weekly loss limits, strategy restrictions (e.g., no naked options)
- [ ] Hybrid autonomy: auto-execute trades below configurable threshold, require approval above it
- [ ] Web dashboard: positions, P&L, agent reasoning/decisions, trade history
- [ ] Real-time alerts via Slack/SMS for trades and risk events
- [ ] Paper trading toggle: switch between live and paper accounts for strategy validation
- [ ] Portfolio-level risk monitoring and reporting

### Out of Scope

- Crypto or forex options — IB equities/ETFs/futures only for v1
- Mobile native app — web dashboard is sufficient
- Social/copy trading features — single-user system
- Backtesting engine — may come in v2 but not blocking v1
- Custom brokerage integrations — IB only

## Context

- User is an active Interactive Brokers account holder, familiar with options trading but hasn't coded against the IB API before
- IB offers TWS API (socket-based) and Client Portal API (REST-based) — both viable integration paths
- Options across equities, ETFs, and futures have different contract specifications, margin requirements, and trading hours that the system must handle
- The LLM + quant hybrid approach means the system needs both real-time market data pipelines (for quant models) and LLM API access (for research/analysis agents)
- Production-ready from v1 means robust error handling, reconnection logic, and order state management are non-negotiable

## Constraints

- **Brokerage**: Interactive Brokers only — all trading, market data, and account management through IB APIs
- **Regulation**: Must respect IB's order rate limits and API usage policies
- **Risk**: Risk management layer must be fail-safe — if risk manager is unreachable, no trades execute
- **Latency**: Options trading doesn't require HFT-level latency, but order execution should be responsive (seconds, not minutes)
- **Cost**: LLM API calls add per-trade cost — agent reasoning should be efficient and avoid unnecessary token usage

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LLM + Quant hybrid over pure LLM | LLMs good at research/synthesis but unreliable for precise pricing; quant models better for signals | — Pending |
| Full agent pipeline over single-agent | Separation of concerns — each agent has clear responsibility, easier to debug and improve | — Pending |
| Hybrid autonomy over full auto | Balances speed for small trades with human oversight for larger risk | — Pending |
| Paper trading toggle over separate system | Same codebase, same pipeline — just switches IB account type for validation | — Pending |

---
*Last updated: 2026-03-25 after initialization*
