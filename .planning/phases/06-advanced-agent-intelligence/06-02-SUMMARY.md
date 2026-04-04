# Phase 6 Plan 02: Expiration Monitor & Rolling Logic Summary

**One-liner:** Deterministic expiration monitoring with DTE/P&L-based rolling decisions using configurable RollingConfig thresholds

## Metadata

- **Phase:** 06-advanced-agent-intelligence
- **Plan:** 02
- **Subsystem:** agents/rolling
- **Tags:** rolling, expiration, options, position-management, deterministic
- **Completed:** 2026-04-04
- **Duration:** 3min

## Dependency Graph

- **Requires:** 06-01 (RegimeConfig pattern in config.py, PipelineState rolling fields)
- **Provides:** ExpirationMonitor, RollingCandidate, RollingDecision, RollingConfig
- **Affects:** 06-03 (pipeline wiring will invoke ExpirationMonitor scan)

## Tech Stack

- **Added:** None (uses existing pydantic, structlog, datetime)
- **Patterns:** Deterministic decision logic (not ML/LLM), Any-typed IB reference for test isolation, serializable dict proposals for PipelineState

## What Was Built

### Task 1: RollingConfig Extension
Added `RollingConfig` Pydantic BaseModel to `config.py` with six configurable fields:
- `enabled` (bool, default True)
- `dte_threshold` (int, default 7, range 1-30)
- `max_loss_multiple` (float, default 2.0, gt 0)
- `preferred_roll_dte` (int, default 30, ge 7)
- `allow_strike_adjustment` (bool, default True)
- `max_roll_attempts` (int, default 3, ge 1)

Added `rolling: RollingConfig` field to `AgentConfig` after the `regime` field.

### Task 2: ExpirationMonitor and Rolling Models
Created `rolling.py` (321 lines) with three components:

**RollingCandidate model:** Captures option position data (symbol, con_id, expiry, DTE, position_size, avg_cost, current_value, unrealized_pnl, right, strike, rolling_reason).

**RollingDecision model:** Records roll/close/hold decision with reasoning, target expiry/strike, and estimated credit/debit.

**ExpirationMonitor class:**
- `scan_expiring_positions()` -- async method querying `ib.positions()`, filtering to OPT with DTE <= threshold, enriching with P&L from `ib.portfolio()`, returning sorted candidates
- `evaluate_rolling()` -- deterministic decision logic: close if loss > max_loss_multiple * avg_cost, hold if profitable with DTE > 1, roll otherwise
- `build_roll_proposals()` -- generates serializable close+open proposal dicts (BUY to close short / SELL to close long, with matching open leg for rolls)

## Key Files

### Created
- `src/trading/agents/rolling.py` -- ExpirationMonitor, RollingCandidate, RollingDecision

### Modified
- `src/trading/agents/config.py` -- RollingConfig class, AgentConfig.rolling field

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Any-typed IB reference | Prevents ib_async import errors in test environments (same pattern as other agents) |
| Deterministic rolling logic (no LLM) | Safety-critical position management must be predictable and testable |
| Close-before-roll safety rule | Positions exceeding max_loss_multiple are closed, not rolled -- trade thesis is invalidated |
| Hold for profitable positions with DTE > 1 | Let theta decay continue when position is working |
| Same strike by default | Strike adjustment deferred without underlying price data; future enhancement can add ITM detection |
| Serializable dict proposals | Matches PipelineState list[dict] pattern for LangGraph checkpoint serialization |

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

All 5 verification criteria passed:
1. Imports work for ExpirationMonitor, RollingCandidate, RollingDecision
2. AgentConfig.rolling and AgentConfig.regime both accessible with defaults
3. RollingCandidate and RollingDecision serialize to dict via model_dump()
4. ExpirationMonitor instantiates with mock IB object
5. evaluate_rolling returns "close" for positions exceeding max_loss_multiple

Comprehensive integration test validated full flow: scan (filters OPT within threshold, enriches P&L) -> evaluate (roll/close/hold logic) -> build_proposals (close+open pairs with correct directions).

## Commits

| Hash | Message |
|------|---------|
| 06b966f | feat(06-02): add RollingConfig and extend AgentConfig |
| b6d6d17 | feat(06-02): add ExpirationMonitor and rolling models |

## Next Phase Readiness

Plan 06-03 will wire ExpirationMonitor.scan_expiring_positions() into the pipeline invocation. The rolling module is fully self-contained and ready for integration:
- ExpirationMonitor accepts Any-typed IB and RollingConfig
- Proposals are serializable dicts ready for PipelineState storage
- PipelineState already has rolling_candidates and rolling_decisions fields (added in 06-01)
