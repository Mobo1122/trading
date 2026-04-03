---
phase: 03-risk-engine
plan: 06
subsystem: risk-wiring-and-tests
tags: [app-lifecycle, risk-engine, circuit-breaker, unit-tests, crash-recovery]
depends_on:
  requires: ["03-01", "03-02", "03-03", "03-04", "03-05"]
  provides: ["TradingApp-risk-wiring", "risk-engine-test-suite"]
  affects: ["04-*", "05-*"]
tech_stack:
  added: []
  patterns: ["lifecycle-wiring", "crash-recovery-on-connect", "mode-specific-limits"]
key_files:
  created:
    - tests/test_risk_engine.py
  modified:
    - src/trading/app.py
    - src/trading/risk/__init__.py
decisions:
  - id: "03-06-01"
    description: "Risk engine components created in startup(), IB ref set in connect_ib()"
    rationale: "Same pattern as Phase 2: create objects in startup, wire IB in connect_ib"
  - id: "03-06-02"
    description: "Circuit breaker load_from_db is non-critical (try/except with warning)"
    rationale: "Same pattern as iv_history.bootstrap and earnings.refresh -- non-fatal on failure"
metrics:
  duration: "6min"
  completed: "2026-04-03"
  tests_added: 53
  total_tests: 179
---

# Phase 3 Plan 6: App Wiring and Risk Engine Tests Summary

**Wire risk engine into application lifecycle and validate all RISK requirements with comprehensive tests.**

## One-Liner

TradingApp creates RiskManager with mode-specific limits on startup; 53 unit tests validate RISK-01 through RISK-07 including circuit breaker crash recovery via fakeredis.

## What Was Done

### Task 1: Wire risk engine into TradingApp lifecycle (3ea2155)

Updated `src/trading/app.py` to integrate the risk engine following the exact same lifecycle pattern used for Phase 2 components:

- **`__init__`**: Added `risk_repository`, `circuit_breaker`, `risk_manager` attributes (None before startup)
- **`startup()`**: After Phase 2 analytics, creates RiskRepository, CircuitBreaker (with mode-specific loss limits), and RiskManager (with full RiskLimitsProfile). Paper/live profile selected based on `settings.trading.mode`
- **`connect_ib()`**: After earnings calendar section, sets `risk_manager._ib` to IB instance and calls `circuit_breaker.load_from_db()` for crash recovery. Both wrapped in try/except for non-fatal failure handling.

Updated `src/trading/risk/__init__.py` to export `CircuitBreaker` and `RiskRepository` for clean external imports.

### Task 2: Comprehensive unit tests (94a2ff4)

Created `tests/test_risk_engine.py` with 53 test cases organized into 8 test classes:

| Category | Tests | RISK Requirement |
|----------|-------|-----------------|
| Position Sizing | 6 | RISK-01 |
| Greeks Exposure | 7 | RISK-02 |
| Strategy Restrictions | 5 | RISK-04 |
| Circuit Breaker | 8 | RISK-03, RISK-07 |
| Margin Check | 9 | RISK-06 |
| RiskManager Integration | 6 | All |
| Fail-Safe | 3 | RISK-05 |
| Config Validation | 9 | All |

Test infrastructure:
- fakeredis.aioredis for Redis mocking in circuit breaker tests
- unittest.mock.AsyncMock for repository and circuit breaker mocking
- pytest.mark.asyncio for async test support
- Follows existing conftest.py patterns (_force_paper_mode, test_settings)

## Decisions Made

1. **Risk engine wiring follows Phase 2 pattern** -- Components created in startup(), IB reference set in connect_ib(). This preserves the separation that allows tests to run without IB Gateway.

2. **Circuit breaker load_from_db is non-critical** -- Wrapped in try/except with warning log, matching the iv_history.bootstrap and earnings.refresh patterns. Trading can proceed even if DB state restore fails (will just start fresh).

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- `python -m pytest tests/test_risk_engine.py -v` -- 53 passed
- `python -m pytest tests/ -x -q` -- 179 passed, 0 failures (no regressions)
- `python -c "from trading.app import TradingApp"` -- OK

## Phase 3 Completion Status

This is plan 6/6 for Phase 3 (Risk Engine). All plans are now complete:

| Plan | Description | Status |
|------|-------------|--------|
| 03-01 | Domain models and config | Complete |
| 03-02 | Position sizing evaluator | Complete |
| 03-03 | Greeks exposure evaluator | Complete |
| 03-04 | Circuit breaker and repository | Complete |
| 03-05 | RiskManager orchestrator | Complete |
| 03-06 | App wiring and tests | Complete |

**Phase 3 delivers:** A complete deterministic risk engine that evaluates every trade proposal against position sizing, Greeks exposure, strategy restrictions, daily/weekly loss limits, and IB margin checks. The fail-safe wrapper guarantees no trade proceeds without explicit approval.

## Next Phase Readiness

Phase 4 (Execution Engine) can proceed. The risk engine is fully wired and tested:
- `RiskManager.check_trade()` is the single entry point for Phase 4 order flow
- `evaluate_with_failsafe()` wraps it for guaranteed rejection on failure
- All 7 RISK requirements validated with automated tests
