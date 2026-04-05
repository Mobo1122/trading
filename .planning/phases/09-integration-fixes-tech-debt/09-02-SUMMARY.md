---
phase: 09-integration-fixes-tech-debt
plan: 02
status: complete
started: 2026-04-05
completed: 2026-04-05
---

## Summary

Resolved 5 tech debt items from the v1 milestone audit: realized P&L publisher, regime timing fix, missing test, and documentation corrections.

## What Was Built

1. **Realized P&L publisher** — DashboardPublisher now accepts `session_factory`, queries `func.sum(ExecutionRecord.realized_pnl)` via SQLAlchemy, and publishes total to `dashboard:realized_pnl` Redis key every cycle. App.py passes session_factory.

2. **Regime detector timing fix** — Moved `t0 = time.monotonic()` before `detect()` call and replaced hardcoded `duration_ms=0` with computed `(time.monotonic() - t0) * 1000`.

3. **Missing commission test** — Added `test_record_commission_updates_record` to TestFillTracker verifying commission and realized_pnl are written to ExecutionRecord.

4. **Phase 8 doc fix** — Corrected body status from `gaps_found` to `passed` in 08-VERIFICATION.md (matching frontmatter).

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Realized P&L publisher + regime timing fix | 92cd20b | publisher.py, app.py, pipeline.py |
| 2 | Missing commission test + doc fix | 85728cd | test_order_execution.py, 08-VERIFICATION.md |

## Test Results

- 1 new test in `tests/test_order_execution.py` — passes
- Full suite: 382 passed, 0 failures

## Decisions

- [09-02]: Local imports in _publish_realized_pnl to avoid circular imports (matching existing fill_tracker pattern)
- [09-02]: Phase 7 research doc route references were already correct — no changes needed
