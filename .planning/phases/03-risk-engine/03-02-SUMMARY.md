---
phase: "03-risk-engine"
plan: "02"
subsystem: "risk"
tags: ["evaluators", "position-sizing", "strategy-restrictions", "naked-options", "pure-functions"]
dependency_graph:
  requires: ["03-01"]
  provides: ["position-sizing-evaluator", "strategy-restriction-evaluator", "naked-options-detection"]
  affects: ["03-03", "03-04", "03-05", "03-06"]
tech_stack:
  added: []
  patterns: ["evaluator-chain-pattern", "pure-function-evaluators"]
key_files:
  created:
    - src/trading/risk/evaluators.py
  modified: []
decisions:
  - id: "03-02-01"
    decision: "existing_positions typed as list[TradeLeg] for reuse without new Position model"
    rationale: "TradeLeg already has symbol, sec_type, action, quantity, right fields needed for coverage checks"
metrics:
  duration: "3min"
  completed: "2026-04-03"
---

# Phase 03 Plan 02: Position Sizing and Strategy Evaluators Summary

Pure-function evaluators for position sizing (dollar/contract/percentage limits) and strategy restrictions (allowlist + naked options detection) following the evaluator chain pattern from RESEARCH.md.

## What Was Built

### evaluate_position_size(proposal, limits) -> RiskDecision | None
Checks three limits in order, short-circuiting on first violation:
1. Dollar limit: `proposal.max_loss` vs `limits.max_dollars`
2. Contract limit: sum of `abs(leg.quantity)` for OPT legs vs `limits.max_contracts`
3. Portfolio percentage: `max_loss / account_value` vs `limits.max_position_pct` (only when account_value > 0)

### is_naked_option(proposal, existing_positions) -> bool
Detects uncovered short options by checking each SELL OPT leg for coverage:
- Covering long option in the same proposal (handles spreads)
- For short calls: sufficient stock in existing_positions (quantity * 100 shares)
- For short puts: long put in existing_positions on same underlying

### evaluate_strategy_restrictions(proposal, restrictions, existing_positions) -> RiskDecision | None
Checks two rules in order:
1. Strategy allowlist: `proposal.strategy_type` must be in `restrictions.allowed_strategies`
2. Naked options: if `allow_naked_options=False`, calls `is_naked_option()` to verify coverage

## Task Execution

| Task | Name | Commit | Status |
|------|------|--------|--------|
| 1 | Position sizing evaluator | a21770f | Done |
| 2 | Strategy restrictions and naked options detection | 9aaed4a | Done |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used TradeLeg for existing_positions type**
- **Found during:** Task 2
- **Issue:** RESEARCH.md references a `Position` type for `existing_positions` that does not exist in the codebase yet
- **Fix:** Typed `existing_positions` as `list[TradeLeg] | None` since TradeLeg already has all needed fields (symbol, sec_type, action, quantity, right)
- **Files modified:** src/trading/risk/evaluators.py
- **Commit:** 9aaed4a

## Verification Results

- All three functions import successfully
- Position sizing rejects over-limit proposals (dollar, contract, percentage) and passes within-limit
- Strategy restrictions reject strategies not in allowlist
- Naked options detection identifies uncovered shorts
- Naked options detection recognizes spreads as covered
- Covered calls with sufficient stock are recognized as covered
- All 126 existing tests pass (no regressions)

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| 03-02-01 | Used `list[TradeLeg]` for existing_positions instead of introducing new Position type | TradeLeg already contains symbol, sec_type, action, quantity, right -- all fields needed for coverage checks. Avoids unnecessary model proliferation. |

## Next Phase Readiness

Plan 03-03 (Greeks evaluators) can proceed -- it follows the same evaluator function pattern established here. The evaluator chain pattern is proven and reusable.
