---
phase: 08-alerts-autonomy
plan: 03
subsystem: pipeline-integration
tags: [approval-gate, threshold-routing, alert-publishing, pipeline, langgraph, redis-pubsub]

dependency_graph:
  requires:
    - phase: 08-01
      provides: AlertRouter, SlackNotifier, SMSNotifier, AlertConfig, AutoExecuteThresholds
    - phase: 08-02
      provides: ApprovalManager with Redis state and timeout-to-reject
  provides:
    - Three-way pipeline routing (executor / approval_gate / END) after risk_manager
    - _exceeds_threshold helper for auto-execute threshold checking
    - Background _await_approval_and_execute task for post-approval execution
    - Redis alert publishing from _executor_node, _risk_node, and circuit_breaker
    - TradingApp wired with AlertRouter, notifiers, and ApprovalManager
  affects:
    - 08-04 (dashboard approval UI submits resolve via ApprovalManager.resolve)
    - 08-05 (Slack interactive buttons submit resolve via ApprovalManager.resolve)

tech_stack:
  added: []
  patterns:
    - "Three-way conditional routing in LangGraph via closure-captured deps"
    - "Non-blocking approval gate: returns pending_approval immediately, spawns asyncio.create_task for resolution"
    - "Alert event publishing from pipeline nodes to Redis pub/sub for AlertRouter consumption"

file_tracking:
  created:
    - tests/test_pipeline_approval.py
  modified:
    - src/trading/agents/pipeline.py
    - src/trading/risk/circuit_breaker.py
    - src/trading/app.py

decisions:
  - id: 08-03-closure-routing
    description: "Used closure-based _make_route_after_risk(deps) for three-way routing instead of modifying the module-level route_after_risk"
    rationale: "The routing function needs deps access for threshold checking; closure pattern avoids global state and keeps the legacy route_after_risk available for backward compatibility"
  - id: 08-03-alert-guard
    description: "All Redis publish calls guarded with if deps.redis_client and try/except"
    rationale: "Alert publishing is non-critical -- must never crash the pipeline; matches established non-fatal pattern from Phase 1"
  - id: 08-03-legacy-route
    description: "Kept module-level route_after_risk for backward compatibility"
    rationale: "Existing tests may import it; the pipeline factory uses the new closure version"

metrics:
  duration: 6min
  completed: 2026-04-05
  tests_passed: 16
  tests_total: 16
---

# Phase 8 Plan 3: Pipeline Approval Gate Integration Summary

**Three-way pipeline routing with auto-execute thresholds, non-blocking approval gate with background execution, and Redis alert publishing from pipeline nodes and circuit breaker, all wired into TradingApp lifecycle**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-05T11:23:28Z
- **Completed:** 2026-04-05T11:29:48Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

### Pipeline Approval Gate (`src/trading/agents/pipeline.py` - 962 lines)

- `PipelineDeps` extended with `approval_manager` and `auto_execute_thresholds` fields
- `_exceeds_threshold()` checks max_loss, delta_impact, vega_impact against AutoExecuteThresholds; returns True (require approval) as safe default when proposal not found
- `_make_route_after_risk(deps)` returns a three-way closure: END (no approvals), "executor" (below threshold or no gate configured), "approval_gate" (above threshold)
- `_approval_gate_node` returns immediately with `pending_approval` status, spawns `_await_approval_and_execute` background task
- `_await_approval_and_execute` calls `_executor_node` on approval, publishes `alerts:trade_rejected` on rejection/timeout, wrapped in try/except (never crashes)
- `_executor_node` publishes `alerts:trade_executed` on submitted results, `alerts:trade_rejected` on failures
- `_risk_node` publishes `alerts:risk_breach` for rejected proposals
- Pipeline graph includes approval_gate node with edge to END
- Backward compatible: routes to executor when no approval_manager or thresholds configured

### Circuit Breaker Alert (`src/trading/risk/circuit_breaker.py` - 331 lines)

- `_activate_halt` publishes `alerts:circuit_breaker` with halt_type, reason, mode, timestamp
- Wrapped in try/except (non-fatal, log warning on failure)

### TradingApp Wiring (`src/trading/app.py` - 639 lines)

- SlackNotifier created when `slack_enabled` and `slack_webhook_url` configured
- SMSNotifier created when `sms_enabled` and all Twilio credentials set
- AlertRouter created with redis, notifiers, and config
- ApprovalManager created with redis and mode-appropriate timeout
- PipelineDeps wired with `approval_manager` and `auto_execute_thresholds`
- AlertRouter started as background task in `connect_ib()`
- Expired approvals recovered via `ApprovalManager.recover_expired()` in `connect_ib()`
- Alert router task cancelled cleanly in `shutdown()`

### Unit Tests (`tests/test_pipeline_approval.py` - 382 lines, 16 tests)

- 6 tests for `_exceeds_threshold`: max_loss, delta, vega exceeds; proposal not found; within thresholds; symbol fallback
- 6 tests for routing: END (no approvals), executor (no manager), executor (no thresholds), executor (below threshold), approval_gate (above threshold), any-exceeds triggers
- 4 tests for `_await_approval_and_execute`: approved calls executor (verifies no double-publish), rejected skips executor, timed_out skips executor, error does not crash

## Task Commits

Each task was committed atomically:

1. **Task 1: Pipeline approval gate and threshold routing** - `8314a91` (feat)
2. **Task 2: Wire alert components into TradingApp lifecycle** - `0a0d25e` (feat)

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Closure-based routing via `_make_route_after_risk(deps)` | Routing function needs deps for threshold checks; closure avoids global state, keeps legacy function |
| All Redis publish calls guarded with `if deps.redis_client` and try/except | Alert publishing is non-critical; matches established non-fatal pattern |
| Kept module-level `route_after_risk` for backward compatibility | Existing tests may import it; pipeline factory uses new closure version |

## Next Phase Readiness

All deliverables for 08-03 are complete. The pipeline approval gate is ready for:
- **08-04:** Dashboard approval UI can call `ApprovalManager.resolve()` to approve/reject trades
- **08-05:** Slack interactive buttons can call `ApprovalManager.resolve()` via Socket Mode handler

No blockers or concerns for downstream plans.

---
*Phase: 08-alerts-autonomy*
*Completed: 2026-04-05*
