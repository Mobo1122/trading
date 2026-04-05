# Requirements Archive: v1 Options Trading AI Agents

**Archived:** 2026-04-05
**Status:** SHIPPED

This is the archived requirements specification for v1.
For current requirements, see `.planning/REQUIREMENTS.md` (created for next milestone).

---

**Defined:** 2026-03-25
**Core Value:** The agents find and execute profitable options trades autonomously while never violating the user's risk constraints

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Brokerage Connectivity

- [x] **CONN-01**: System connects to IB Gateway with auto-reconnect and daily restart handling
- [x] **CONN-02**: System places market, limit, and stop orders via IB API
- [x] **CONN-03**: System places multi-leg combo/spread orders (up to 6 legs)
- [x] **CONN-04**: System tracks order state via local state machine (pending -> submitted -> filled/cancelled/error)
- [x] **CONN-05**: System toggles between paper and live trading via configuration
- [x] **CONN-06**: System retrieves option chains (strikes, expirations, contract specs) for equities, ETFs, and futures

### Risk Management

- [x] **RISK-01**: System enforces configurable position sizing limits (max % portfolio, max contracts, max dollar amount per trade)
- [x] **RISK-02**: System enforces portfolio-level Greeks exposure limits (delta, gamma, theta, vega caps)
- [x] **RISK-03**: System enforces daily and weekly loss limits that halt all new trading when breached
- [x] **RISK-04**: System enforces strategy restrictions (e.g., no naked options) via configurable allowlist
- [x] **RISK-05**: System blocks all trades when risk manager is unreachable (fail-safe)
- [x] **RISK-06**: System performs pre-trade margin check before order submission
- [x] **RISK-07**: Loss limits and circuit breaker state persist across system restarts

### Market Data & Analytics

- [x] **DATA-01**: System streams real-time quotes (bid/ask, last, volume) from IB
- [x] **DATA-02**: System streams real-time per-contract Greeks (delta, gamma, theta, vega) and IV
- [x] **DATA-03**: System provides options open interest and volume for liquidity assessment
- [x] **DATA-04**: System calculates IV rank and IV percentile vs 52-week history per underlying
- [x] **DATA-05**: System integrates earnings calendar and adjusts strategy for IV expansion/crush events

### Agent Pipeline

- [x] **AGENT-01**: Scanner agent identifies options opportunities across equities, ETFs, and futures
- [x] **AGENT-02**: Strategist agent constructs trade proposals (strategy type + strike/expiration selection)
- [x] **AGENT-03**: Risk manager agent validates trade proposals against all risk rules
- [x] **AGENT-04**: Executor agent places validated trades via IB API
- [x] **AGENT-05**: Full pipeline runs as scanner -> strategist -> risk manager -> executor via LangGraph orchestration
- [x] **AGENT-06**: Every agent decision is logged with full reasoning chain in natural language
- [x] **AGENT-07**: Scanner detects market regime (bull/bear/sideways/volatile) and adapts strategy mix
- [x] **AGENT-08**: System automatically rolls expiring positions to new expiration when appropriate

### Dashboard & Monitoring

- [x] **DASH-01**: Web dashboard displays all positions with real-time P&L (per-position and portfolio)
- [x] **DASH-02**: Dashboard displays portfolio-level aggregated Greeks (delta, gamma, theta, vega)
- [x] **DASH-03**: Dashboard shows full trade history with timestamps, fills, and reasoning
- [x] **DASH-04**: Dashboard shows each agent's reasoning chain for every trade decision
- [x] **DASH-05**: Dashboard shows system health (connection status, agent heartbeats, data freshness)
- [x] **DASH-06**: Dashboard provides P&L scenario analysis (what-if: underlying +/-X%, IV +/-Y%, T+N days)

### Alerts & Autonomy

- [x] **AUTO-01**: System sends Slack/SMS alerts for trade executions, risk events, and system errors
- [x] **AUTO-02**: System auto-executes trades below configurable threshold (dollar amount, Greeks impact)
- [x] **AUTO-03**: System presents approval workflow for trades above threshold with full context
- [x] **AUTO-04**: Approval requests timeout to reject (safe default) if no human response
- [x] **AUTO-05**: User can approve/reject trades via Slack interactive buttons

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Analytics

- **ADVN-01**: Volatility surface and skew analysis for mispriced options detection
- **ADVN-02**: Unusual options activity detection (volume > 5x average, block trades, sweeps)
- **ADVN-03**: Correlation awareness across positions to prevent overconcentration
- **ADVN-04**: Dynamic hedge suggestions when portfolio Greeks drift

### Enhanced Intelligence

- **INTL-01**: Strategy performance attribution by agent, strategy type, and market regime
- **INTL-02**: Backtesting engine for running strategies against historical data

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Crypto/forex options | IB equities/ETFs/futures only for v1; different exchanges and data sources |
| Mobile native app | Web dashboard + Slack covers mobile needs; massive engineering surface |
| Social/copy trading | Single-user system; multi-tenancy adds auth, compliance, and community complexity |
| Custom options pricing models | IB Greeks + open-source libs sufficient; custom pricing is PhD-level quant work |
| HFT/sub-second latency | Options bid-ask spreads are wide; IB has 50 msg/sec limit; focus on decision quality |
| Desktop GUI application | Web dashboard accessible from any device; no advantage over browser |
| Real-time alternative data as blocking dependency | Build core first; LLM agents can use news when available but must function without it |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONN-01 | Phase 1 | Complete |
| CONN-02 | Phase 4 | Complete |
| CONN-03 | Phase 4 | Complete |
| CONN-04 | Phase 1 | Complete |
| CONN-05 | Phase 1 | Complete |
| CONN-06 | Phase 1 | Complete |
| RISK-01 | Phase 3 | Complete |
| RISK-02 | Phase 3 | Complete |
| RISK-03 | Phase 3, 9 | Complete |
| RISK-04 | Phase 3 | Complete |
| RISK-05 | Phase 3 | Complete |
| RISK-06 | Phase 3 | Complete |
| RISK-07 | Phase 3, 9 | Complete |
| DATA-01 | Phase 2 | Complete |
| DATA-02 | Phase 2 | Complete |
| DATA-03 | Phase 2 | Complete |
| DATA-04 | Phase 2 | Complete |
| DATA-05 | Phase 2 | Complete |
| AGENT-01 | Phase 5, 9 | Complete |
| AGENT-02 | Phase 5, 9 | Complete |
| AGENT-03 | Phase 5 | Complete |
| AGENT-04 | Phase 5 | Complete |
| AGENT-05 | Phase 5 | Complete |
| AGENT-06 | Phase 5 | Complete |
| AGENT-07 | Phase 6, 9 | Complete |
| AGENT-08 | Phase 6, 10 | Complete |
| DASH-01 | Phase 7, 9 | Complete |
| DASH-02 | Phase 7 | Complete |
| DASH-03 | Phase 7 | Complete |
| DASH-04 | Phase 7 | Complete |
| DASH-05 | Phase 7, 9 | Complete |
| DASH-06 | Phase 7 | Complete |
| AUTO-01 | Phase 8 | Complete |
| AUTO-02 | Phase 8 | Complete |
| AUTO-03 | Phase 8 | Complete |
| AUTO-04 | Phase 8 | Complete |
| AUTO-05 | Phase 8 | Complete |

**Coverage:**
- v1 requirements: 37 total
- Shipped: 37 (100%)
- Adjusted: 0
- Dropped: 0

---

## Milestone Summary

**Shipped:** 37 of 37 v1 requirements
**Adjusted:** None — all requirements shipped as originally specified
**Dropped:** None

**Notes:**
- RISK-03, RISK-07 required Phase 9 fix (FillTracker → CircuitBreaker wiring) to be fully operational
- AGENT-01, AGENT-02, AGENT-07 required Phase 9 fix (Redis namespace mismatch) for live data access
- AGENT-08 required Phase 10 (rolling pipeline node) to complete the end-to-end rolling flow
- DASH-01, DASH-05 required Phase 9 fixes (realized P&L publisher, health monitor) for full dashboard accuracy

---
*Archived: 2026-04-05 as part of v1 milestone completion*
