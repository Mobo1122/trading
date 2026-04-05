---
milestone: v1
audited: 2026-04-05T18:00:00Z
status: gaps_found
scores:
  requirements: 31/37
  phases: 8/8
  integration: 3/6
  flows: 2/6
gaps:
  requirements:
    - "RISK-03: record_realized_loss never called — loss limits never auto-trigger"
    - "RISK-07: Loss persistence works but nothing accumulates (same root cause as RISK-03)"
    - "AGENT-01: Scanner reads market_data:{symbol} but distributor writes mktdata:latest:quote:{symbol}"
    - "AGENT-02: Strategist reads same wrong namespace (market_data:{symbol})"
    - "AGENT-07: RegimeDetector price_data empty due to same namespace mismatch"
    - "DASH-05: HealthMonitor.current_health property does not exist — pipeline status always idle"
  integration:
    - "Redis namespace mismatch: agents read market_data:{symbol}, distributor writes mktdata:latest:quote:{symbol}"
    - "CircuitBreaker.record_realized_loss has zero callers in production code"
    - "DashboardPublisher accesses HealthMonitor.current_health which does not exist"
  flows:
    - "Flow 3 (Risk Halt): Loss breach → circuit breaker never triggers automatically"
    - "Flow 1 (Trade Pipeline): Agents operate without live price context"
    - "Flow 5 (Regime Adaptation): Price momentum data always empty"
tech_debt:
  - phase: 01-ib-connectivity-infrastructure
    items:
      - "ContractResolver not instantiated in TradingApp (by design — on-demand use)"
      - "Runtime confirmation needed: Docker/IB Gateway for TimescaleDB migration, auto-reconnect, futures chains"
  - phase: 04-order-execution
    items:
      - "Missing test_record_commission_updates_record unit test (coverage omission)"
  - phase: 06-advanced-agent-intelligence
    items:
      - "regime_detector duration_ms hardcoded to 0 (t0 assigned after detect() but never used)"
  - phase: 07-dashboard-monitoring
    items:
      - "dashboard:realized_pnl Redis key never written — portfolio realized P&L always 0"
      - "API route documented as GET /api/trades but actual path is GET /api/trades/history (frontend correct)"
  - phase: 08-alerts-autonomy
    items:
      - "Phase 8 VERIFICATION.md has status discrepancy: frontmatter says passed, body says gaps_found (gap was fixed in commit 853b6f6)"
---

# v1 Milestone Audit Report

**Milestone:** v1 — Options Trading AI Agents
**Audited:** 2026-04-05
**Status:** gaps_found
**Definition of Done:** The agents find and execute profitable options trades autonomously while never violating the user's risk constraints

## Executive Summary

All 8 phases passed individual verification. All 37 v1 requirements have implementations. However, the cross-phase integration check revealed **3 critical wiring gaps** that prevent 6 requirements from being fully satisfied in production. These are not missing features — the code exists in each phase — but the connections between phases have namespace mismatches or missing call sites.

| Category | Score | Details |
|----------|-------|---------|
| Requirements | 31/37 | 6 partial (3 root causes) |
| Phases | 8/8 | All passed individual verification |
| Integration | 3/6 | 3 critical cross-phase wiring gaps |
| E2E Flows | 2/6 complete | 3 partial, 1 broken |

---

## Critical Gaps (Blockers)

### Gap 1: Redis Namespace Mismatch — Agents Can't Read Market Data

**Root cause:** Phase 2's `RedisDistributor` writes market data to `mktdata:latest:quote:{symbol}`, but Phase 5/6 agents read from `market_data:{symbol}`.

| File | Line | Reads | Should Read |
|------|------|-------|-------------|
| `src/trading/agents/scanner.py` | 139 | `market_data:{symbol}` | `mktdata:latest:quote:{symbol}` |
| `src/trading/agents/strategist.py` | 146 | `market_data:{symbol}` | `mktdata:latest:quote:{symbol}` |
| `src/trading/agents/pipeline.py` | 181 | `market_data:{symbol}` | `mktdata:latest:quote:{symbol}` |

**Impact:** All three agents (scanner, strategist, regime detector) receive empty dicts for market data at runtime. They degrade gracefully but operate without real-time price context, silently producing lower-quality decisions.

**Requirements affected:** AGENT-01, AGENT-02, AGENT-07

**Fix:** Change all three Redis key references from `market_data:{symbol}` to `mktdata:latest:quote:{symbol}`.

---

### Gap 2: Circuit Breaker Loss Accumulation Never Triggered

**Root cause:** `CircuitBreaker.record_realized_loss(loss_amount)` (defined at `src/trading/risk/circuit_breaker.py:111`) has zero callers in production code. `FillTracker` receives fill events with P&L but never calls into the circuit breaker.

**Impact:** The loss-limit circuit breaker accumulates no state and will never self-trigger. Daily/weekly loss limits exist as configuration but are functionally inert. The circuit breaker can only be triggered via manual Redis manipulation or the `emergency_halt` config flag.

**Requirements affected:** RISK-03, RISK-07

**Fix:** Add a call to `circuit_breaker.record_realized_loss()` in `FillTracker.record_fill()` when a fill results in a realized loss (position close), or wire it through `OrderExecutionService` post-fill.

---

### Gap 3: HealthMonitor.current_health Property Missing

**Root cause:** `DashboardPublisher._publish_pipeline_status()` at `src/trading/dashboard/publisher.py:123` accesses `self._health_monitor.current_health`, but `HealthMonitor` (in `src/trading/core/health.py`) only exposes `check_health()` (an async method). The `except Exception: pass` silently swallows the `AttributeError`.

**Impact:** `dashboard:pipeline_status` always writes `"idle"` regardless of actual system state. The pipeline status indicator in the Health panel is permanently stale.

**Requirements affected:** DASH-05 (partially — IB/DB/Redis status and data freshness work; only pipeline status is broken)

**Fix:** Either add a `current_health` cached property to `HealthMonitor`, or change `_publish_pipeline_status` to `await self._health_monitor.check_health()`.

---

## Requirements Coverage

### Brokerage Connectivity (Phase 1, 4)

| Requirement | Status | Notes |
|-------------|--------|-------|
| CONN-01: Auto-reconnect with daily restart | SATISFIED | Code verified; runtime needs IB Gateway |
| CONN-02: Market/limit/stop orders via IB | SATISFIED | 25 tests pass |
| CONN-03: Multi-leg combo/spread orders (up to 6 legs) | SATISFIED | BAG construction with MAX_LEGS=6 |
| CONN-04: Order state machine with DB persistence | SATISFIED | 9 states, 11 transitions, 35 tests |
| CONN-05: Paper/live toggle via config | SATISFIED | TRADING_MODE env var + YAML overlays |
| CONN-06: Option chains for equities/ETFs/futures | SATISFIED | STK/IND/FUT dispatch; FUT path untested at runtime |

### Risk Management (Phase 3)

| Requirement | Status | Notes |
|-------------|--------|-------|
| RISK-01: Position sizing limits | SATISFIED | Dollar, contract, portfolio-% checks |
| RISK-02: Greeks exposure caps | SATISFIED | Delta/gamma/theta/vega with sign semantics |
| RISK-03: Daily/weekly loss limits halt trading | **PARTIAL** | Circuit breaker works in isolation; `record_realized_loss` never called (Gap 2) |
| RISK-04: Strategy restrictions (no naked options) | SATISFIED | Allowlist + naked detection |
| RISK-05: Fail-safe when risk manager unreachable | SATISFIED | `evaluate_with_failsafe` wraps with timeout |
| RISK-06: Pre-trade margin check | SATISFIED | `whatIfOrder` with configurable timeout |
| RISK-07: Loss limits persist across restarts | **PARTIAL** | Persistence works but nothing accumulates (same root cause as RISK-03) |

### Market Data & Analytics (Phase 2)

| Requirement | Status | Notes |
|-------------|--------|-------|
| DATA-01: Real-time quotes from IB | SATISFIED | reqMktData + pendingTickersEvent pipeline |
| DATA-02: Per-contract Greeks and IV | SATISFIED | modelGreeks extraction for OPT contracts |
| DATA-03: Open interest and volume | SATISFIED | In QuoteSnapshot via Redis |
| DATA-04: IV rank and IV percentile | SATISFIED | IVEngine with 52-week history |
| DATA-05: Earnings calendar with IV awareness | SATISFIED | Finnhub integration with EarningsFlag |

### Agent Pipeline (Phase 5, 6)

| Requirement | Status | Notes |
|-------------|--------|-------|
| AGENT-01: Scanner identifies opportunities | **PARTIAL** | Agent works but gets empty market data at runtime (Gap 1) |
| AGENT-02: Strategist constructs proposals | **PARTIAL** | Agent works but gets empty market data at runtime (Gap 1) |
| AGENT-03: Risk manager validates proposals | SATISFIED | Deterministic-first with Phase 3 RiskManager |
| AGENT-04: Executor places validated trades | SATISFIED | Calls OrderExecutionService.submit_order |
| AGENT-05: LangGraph pipeline with checkpoints | SATISFIED | StateGraph with conditional routing |
| AGENT-06: Decision logging with reasoning | SATISFIED | AgentDecisionLog with 8 call sites |
| AGENT-07: Regime detection adapts strategy mix | **PARTIAL** | RegimeDetector works but price_data empty (Gap 1) |
| AGENT-08: Automatic position rolling | SATISFIED | ExpirationMonitor + pipeline integration |

### Dashboard & Monitoring (Phase 7)

| Requirement | Status | Notes |
|-------------|--------|-------|
| DASH-01: Positions with real-time P&L | SATISFIED | Positions + unrealized P&L work; realized P&L always 0 (tech debt) |
| DASH-02: Portfolio Greeks in real time | SATISFIED | SCAN + HGETALL aggregation + WebSocket push |
| DASH-03: Trade history with fill details | SATISFIED | Paginated with Order → AgentDecisionLog join |
| DASH-04: Agent reasoning chain per trade | SATISFIED | proposal_id/run_id linkage; reasoning-chain component |
| DASH-05: System health indicators | **PARTIAL** | IB/DB/Redis/freshness work; pipeline status always "idle" (Gap 3) |
| DASH-06: P&L scenario analysis | SATISFIED | Black-Scholes engine with interactive UI |

### Alerts & Autonomy (Phase 8)

| Requirement | Status | Notes |
|-------------|--------|-------|
| AUTO-01: Slack/SMS alerts for executions, risk, errors | SATISFIED | system_error publisher added (commit 853b6f6) |
| AUTO-02: Auto-execute below threshold | SATISFIED | Three-way routing in pipeline |
| AUTO-03: Approval workflow above threshold | SATISFIED | Full context with Greeks/P&L |
| AUTO-04: Timeout-to-reject safe default | SATISFIED | asyncio.wait with timeout |
| AUTO-05: Slack interactive buttons | SATISFIED | slack-bolt Socket Mode |

---

## E2E Flow Verification

### Flow 1: Trade Pipeline
**Path:** Market data → Scanner → Strategist → Risk Manager → Executor → IB → Fill → Dashboard
**Status:** PARTIAL
**Break:** Agents read `market_data:{symbol}` (empty) instead of `mktdata:latest:quote:{symbol}`. Pipeline runs but agents lack live price context. Additionally, `dashboard:realized_pnl` is never written so portfolio realized P&L is always 0.

### Flow 2: Approval
**Path:** Above-threshold trade → Approval gate → Slack/Dashboard → Approve/Reject → Execute
**Status:** COMPLETE
**Evidence:** Full chain verified: `_approval_gate_node` → `ApprovalManager.request_approval` → Redis hash + `alerts:approval_request` → `AlertRouter` → `SlackNotifier` with Block Kit buttons → `slack_bot handle_approve/reject` → `approval_manager.resolve()` → `_await_approval_and_execute` → `_executor_node`. Dashboard path also verified.

### Flow 3: Risk Halt
**Path:** Loss breach → Circuit breaker → All trading halts → Persists across restart → Alert sent
**Status:** BROKEN
**Break:** `record_realized_loss` has zero callers. Loss events from fills never reach the circuit breaker. The halt mechanism works if called directly, but the production wiring from FillTracker → CircuitBreaker does not exist.

### Flow 4: Dashboard Real-Time
**Path:** IB data → Redis pub/sub → DashboardPublisher → WebSocket → Browser
**Status:** PARTIAL
**Break:** Positions, Greeks, and health data flow correctly. Pipeline status is always "idle" because `HealthMonitor.current_health` doesn't exist (silently caught).

### Flow 5: Regime Adaptation
**Path:** Market data → RegimeDetector → Scanner prompt injection → Adapted strategy mix
**Status:** PARTIAL
**Break:** IV data flows correctly via `iv_engine.compute_batch()`. Price momentum data is empty due to the `market_data:{symbol}` namespace mismatch. Regime classification defaults to SIDEWAYS/UNKNOWN regardless of actual market conditions.

### Flow 6: Position Rolling
**Path:** Expiring position → ExpirationMonitor → Rolling candidates → Pipeline state
**Status:** COMPLETE
**Evidence:** `ExpirationMonitor` created in `app.py:445`, injected into `pipeline_deps`. `run_agent_pipeline()` calls `scan_expiring_positions()`, serializes results, passes into `run_pipeline(rolling_candidates=...)`.

---

## Phase Verification Summary

| Phase | Status | Score | Critical Gaps | Tech Debt Items |
|-------|--------|-------|---------------|-----------------|
| 1. IB Connectivity | human_needed | 5/5 | 0 | 2 (runtime confirmation needed) |
| 2. Market Data | passed | 5/5 | 0 | 0 |
| 3. Risk Engine | passed | 5/5 | 0 | 0 |
| 4. Order Execution | passed | 4/4 | 0 | 1 (missing commission test) |
| 5. Core Agent Pipeline | passed | 5/5 | 0 | 0 |
| 6. Advanced Intelligence | passed | 3/3 | 0 | 1 (timing bug) |
| 7. Dashboard | passed | 5/5 | 0 | 2 (realized P&L, doc mismatch) |
| 8. Alerts & Autonomy | passed | 5/5 | 0 | 1 (verification status discrepancy) |

Note: All phases pass their own verification. The 3 critical gaps are **cross-phase integration issues** discovered by the integration checker, not phase-internal failures.

---

## Tech Debt Summary

### Phase 1: IB Connectivity & Infrastructure
- ContractResolver not instantiated in TradingApp (by design — on-demand use)
- Runtime confirmation needed: Docker/IB Gateway for TimescaleDB migration, auto-reconnect, futures chains

### Phase 4: Order Execution
- Missing `test_record_commission_updates_record` unit test (coverage omission, not a feature gap)

### Phase 6: Advanced Agent Intelligence
- `t0 = time.monotonic()` assigned after `detect()` but never used — `duration_ms` hardcoded to 0 for regime_detector stage

### Phase 7: Dashboard & Monitoring
- `dashboard:realized_pnl` Redis key never written — portfolio realized P&L always 0
- API route documented as `GET /api/trades` but actual path is `GET /api/trades/history` (frontend is correct)

### Phase 8: Alerts & Autonomy
- VERIFICATION.md has status discrepancy: frontmatter says `passed`, body says `gaps_found` (gap was fixed in commit 853b6f6 but verification not updated)

**Total:** 7 tech debt items across 5 phases

---

## Recommendations

### Critical (must fix before production)

1. **Fix Redis namespace mismatch** — Change `market_data:{symbol}` → `mktdata:latest:quote:{symbol}` in scanner.py, strategist.py, and pipeline.py. This is a 3-line fix that unblocks 3 requirements and 2 E2E flows.

2. **Wire FillTracker → CircuitBreaker** — Add `circuit_breaker.record_realized_loss()` call when fills result in realized losses. This completes the loss-limit halt mechanism and unblocks 2 requirements and 1 E2E flow.

3. **Fix HealthMonitor.current_health** — Either add a cached property to HealthMonitor or change DashboardPublisher to use `check_health()`. This completes the system health dashboard requirement.

### Non-critical (track in backlog)

4. Add `dashboard:realized_pnl` writer to track portfolio realized P&L
5. Fix regime_detector duration_ms timing
6. Add missing commission unit test
7. Update Phase 8 VERIFICATION.md status consistency

---

_Audited: 2026-04-05_
_Auditor: Claude (gsd milestone auditor)_
