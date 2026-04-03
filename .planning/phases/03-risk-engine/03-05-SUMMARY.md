---
phase: 03-risk-engine
plan: 05
subsystem: risk-orchestration
tags: [risk-manager, margin-check, evaluator-chain, fail-safe, whatIfOrder]
depends_on:
  requires: ["03-01", "03-02", "03-03", "03-04"]
  provides: ["RiskManager", "evaluate_with_failsafe", "check_margin", "evaluate_margin"]
  affects: ["03-06", "04-*", "05-*"]
tech_stack:
  added: []
  patterns: ["evaluator-chain-orchestrator", "fail-safe-wrapper", "timeout-passthrough"]
key_files:
  created:
    - src/trading/risk/margin_check.py
    - src/trading/risk/manager.py
  modified:
    - src/trading/risk/__init__.py
decisions:
  - id: "03-05-01"
    description: "Per-leg margin checks rather than combo orders (RESEARCH.md recommendation)"
  - id: "03-05-02"
    description: "Persistence errors are non-fatal -- log warning, continue evaluation"
  - id: "03-05-03"
    description: "Margin check returns first leg result only (iterates legs, returns on first with contract/order)"
metrics:
  duration: "4min"
  completed: "2026-04-03"
  tasks: 2
  commits: 2
---

# Phase 3 Plan 5: RiskManager Orchestrator Summary

**RiskManager chains all evaluators (emergency -> circuit breaker -> position -> greeks -> strategy -> margin) with short-circuit, plus evaluate_with_failsafe wrapping the entire evaluation in a timeout that rejects on any failure.**

## What Was Built

### Task 1: whatIfOrder Margin Check Wrapper
- `check_margin(ib, contract, order, timeout)` wraps `whatIfOrderAsync` with `asyncio.wait_for`
- `_parse_margin_str(value)` handles IB's string-typed margin fields, converting empty/None/UNSET_DOUBLE (>1e300) to None
- `evaluate_margin(margin_result, account_value)` rejects on negative equity or excess initial margin
- Timeout is treated as pass-through (non-blocking) -- a timed-out margin check does not block a trade
- Commission parsing includes UNSET_DOUBLE sentinel check

### Task 2: RiskManager Orchestrator
- `RiskManager.__init__` takes limits, circuit_breaker, repository, optional ib, and mode
- `check_trade(proposal, dry_run, current_portfolio_greeks, existing_positions)` runs the full evaluator chain:
  1. Emergency halt (config flag)
  2. Circuit breaker auto-reset (market open handling)
  3. Circuit breaker check (daily/weekly loss limits)
  4. Position sizing (dollars, contracts, portfolio %)
  5. Greeks exposure (delta, gamma, theta, vega)
  6. Strategy restrictions (allowlist, naked options)
  7. Margin check (IB whatIfOrder, only if connected)
- Short-circuits on first violation for efficiency
- Every decision (approved/rejected, dry-run/real) persisted via repository
- `evaluate_with_failsafe(risk_manager, proposal, timeout)` wraps check_trade with asyncio.wait_for; returns RISK_MANAGER_UNAVAILABLE rejection on ANY exception
- `__init__.py` updated to export RiskManager and evaluate_with_failsafe

## Decisions Made

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Per-leg margin checks, not combo orders | RESEARCH.md Open Question 1: per-leg calls may overstate margin but combo whatIfOrder support is inconsistent. Conservative is safe. |
| 2 | Persistence errors non-fatal (try/except in _persist) | A DB write failure should not prevent risk evaluation from completing. Log warning and continue. |
| 3 | First leg with contract/order gets margin check | Iterates legs, returns result from first eligible leg. Keeps margin check simple for initial implementation. |

## Deviations from Plan

None -- plan executed exactly as written.

## Commit Log

| Commit | Type | Description |
|--------|------|-------------|
| bf7e7cb | feat | whatIfOrder margin check wrapper |
| c4a4c48 | feat | RiskManager orchestrator with evaluator chain and fail-safe |

## Verification Results

- `from trading.risk.manager import RiskManager, evaluate_with_failsafe` -- OK
- `from trading.risk.margin_check import check_margin, evaluate_margin` -- OK
- Margin string parsing handles UNSET_DOUBLE, empty, None, valid floats -- OK
- Timeout pass-through verified -- OK
- Insufficient equity rejection verified -- OK
- Evaluator chain order: emergency -> circuit breaker -> position -> greeks -> strategy -> margin -- OK
- evaluate_with_failsafe returns RISK_MANAGER_UNAVAILABLE on exception -- OK
- All 126 existing tests pass -- OK

## Next Phase Readiness

Plan 03-06 (integration wiring) can proceed. All risk engine components are now complete:
- Models (03-01), Evaluators (03-02), Greeks (03-03), Circuit Breaker + Repository (03-04), and now RiskManager + Margin Check (03-05)
- The RiskManager is the single entry point that Phase 4 and Phase 5 will consume
