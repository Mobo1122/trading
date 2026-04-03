---
phase: 03-risk-engine
plan: 04
subsystem: risk-state
tags: [circuit-breaker, redis, postgres, loss-limits, crash-recovery]
depends_on: ["03-01"]
provides: ["circuit-breaker", "risk-repository", "loss-tracking", "halt-persistence"]
affects: ["03-05", "03-06"]
tech_stack:
  added: []
  patterns: ["dual-storage (Redis+Postgres)", "atomic Redis increments", "upsert via select+update/insert", "ET timezone reset logic"]
key_files:
  created:
    - src/trading/risk/repository.py
    - src/trading/risk/circuit_breaker.py
  modified: []
decisions:
  - "Upsert via select+update/insert instead of session.merge() for clearer control flow"
  - "emergency_halt accepted as constructor param (not fetched from config at check time)"
  - "Daily/weekly resets keyed by date string comparison in Redis for idempotent reset"
  - "loss_amount <= 0 silently returns (no-op) rather than raising"
metrics:
  duration: 3min
  completed: 2026-04-03
---

# Phase 3 Plan 4: Circuit Breaker and Risk Repository Summary

**Dual-storage circuit breaker (Redis hot-path + Postgres crash recovery) with atomic HINCRBYFLOAT loss tracking and independent daily/weekly auto-reset at 9:30am ET.**

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Risk repository for DB persistence | 8d69aa2 | src/trading/risk/repository.py |
| 2 | Circuit breaker with dual-storage state management | c1571cb | src/trading/risk/circuit_breaker.py |

## What Was Built

### RiskRepository (`repository.py`)
- **save_decision()**: Maps RiskDecision Pydantic model (including nested MarginResult subfields) to flat RiskDecisionRecord ORM row and persists via async session.
- **save_circuit_breaker_state()**: Upserts CircuitBreakerState by (mode, halt_type) unique constraint. Uses select+update for existing rows, insert for new rows.
- **load_circuit_breaker_state()**: Loads all breaker records for a mode (daily + weekly) for startup recovery.
- Uses get_session context manager for automatic commit/rollback/close.

### CircuitBreaker (`circuit_breaker.py`)
- **check()**: Reads Redis hash for halt flags. Returns rejection RiskDecision for emergency halt, daily halt, or weekly halt. Returns None if clear.
- **record_realized_loss()**: Atomic HINCRBYFLOAT on both daily and weekly accumulators. Checks thresholds after increment and activates halt if exceeded.
- **_activate_halt()**: Sets halt flag + timestamp in Redis, reads current loss values, persists full state to Postgres via repository.
- **load_from_db()**: Startup recovery -- loads Postgres state and writes into Redis hash so halts survive Redis restarts.
- **check_and_reset()**: Auto-reset at 9:30am ET. Daily reset clears daily loss/halt only. Weekly reset (Monday) clears weekly loss/halt only. Independent per RESEARCH.md Pitfall 5.

### Redis Key Structure
- Key: `risk:circuit_breaker:{mode}` (hash)
- Fields: `daily_realized_loss`, `weekly_realized_loss`, `daily_halted`, `weekly_halted`, `halted_at`, `last_reset_daily`, `last_reset_weekly`

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Upsert via select+update/insert instead of merge() | Clearer control flow; merge() behavior with autoincrement PKs can be surprising |
| emergency_halt as constructor param | Avoids re-reading config on every check(); set once at init, updated when config changes |
| Date string comparison for reset idempotency | Simple, no extra Redis keys needed; comparing today's date string ensures reset happens exactly once per period |
| Positive loss_amount guard (no-op on <= 0) | Prevents accidental negative decrements; callers don't need to pre-validate |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Upsert implementation approach**
- **Found during:** Task 1
- **Issue:** Plan specified session.merge() for upsert, but merge() with autoincrement PKs and unique constraints can produce duplicate inserts if the ORM instance lacks the correct PK
- **Fix:** Used select+update for existing rows, insert for new rows -- explicit and safe
- **Files modified:** src/trading/risk/repository.py
- **Commit:** 8d69aa2

## Verification Results

- Both imports succeed: `from trading.risk.circuit_breaker import CircuitBreaker; from trading.risk.repository import RiskRepository`
- CircuitBreaker uses HINCRBYFLOAT for atomic loss accumulation (2 calls per loss event)
- Halt state persisted to both Redis (fast reads) and Postgres (crash recovery)
- load_from_db restores halt state from Postgres to Redis on startup
- Daily reset does NOT clear weekly halt; weekly reset does NOT clear daily halt
- All 126 existing tests pass

## Next Phase Readiness

Plan 03-05 (RiskManager orchestrator) can now:
- Use CircuitBreaker.check() in the evaluation pipeline
- Use CircuitBreaker.record_realized_loss() when trades close
- Use RiskRepository.save_decision() to log all evaluations
- Call CircuitBreaker.load_from_db() on startup
- Call CircuitBreaker.check_and_reset() periodically
