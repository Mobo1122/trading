---
phase: 08-alerts-autonomy
plan: 02
subsystem: alerts
tags: [asyncio, redis, pubsub, approval-workflow, future, timeout]

# Dependency graph
requires:
  - phase: 01-ib-connectivity
    provides: Redis client factory (decode_responses=True)
  - phase: 02-market-data-analytics
    provides: Redis dual-write pub/sub pattern
  - phase: 05-core-agent-pipeline
    provides: PipelineState TypedDict, pipeline graph
provides:
  - ApprovalManager class with Redis state, asyncio.Future timeout, pub/sub cross-process resolution
  - request_approval, resolve, get_pending, recover_expired methods
  - PipelineState extended with approval_status and approval_id fields
affects:
  - 08-03 (approval gate pipeline node uses ApprovalManager)
  - 08-04 (dashboard approval UI calls ApprovalManager.resolve)
  - 08-05 (Slack interactive buttons call ApprovalManager.resolve)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Approval state machine: pending -> approved|rejected|timed_out via Redis hash + asyncio.Future"
    - "Cross-process resolution via Redis pub/sub listener on alerts:approval_resolved"
    - "Startup recovery: scan Redis for expired pending approvals, auto-reject"

key-files:
  created:
    - src/trading/alerts/approval.py
    - tests/test_approval_manager.py
  modified:
    - src/trading/agents/state.py
    - src/trading/agents/pipeline.py

key-decisions:
  - "asyncio.wait (not wait_for) with explicit listener_task for clean cancellation on both timeout and cross-process resolution paths"
  - "Redis key TTL = timeout + 3600s for dashboard visibility after expiration"
  - "scan_iter (not KEYS) for get_pending -- production-safe Redis enumeration"

patterns-established:
  - "Approval lifecycle: Redis hash for persistence + asyncio.Future for in-process signaling + pub/sub for cross-process"

# Metrics
duration: 3min
completed: 2026-04-05
---

# Phase 8 Plan 2: Approval Manager Summary

**ApprovalManager with Redis-persisted state, asyncio.Future timeout-to-reject, cross-process pub/sub resolution, and startup expired-approval recovery**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-05T11:15:50Z
- **Completed:** 2026-04-05T11:18:57Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- ApprovalManager stores pending approval state in Redis hash with full trade context, waits via asyncio.Future with configurable timeout, and auto-rejects on timeout (safe default)
- Cross-process resolution via Redis pub/sub listener enables dashboard and Slack to resolve approvals in separate processes
- recover_expired() scans Redis on startup and auto-rejects stale approvals from previous process crashes
- PipelineState extended with approval_status and approval_id for pipeline approval gate integration
- 10 comprehensive unit tests with fakeredis covering all approval lifecycle paths

## Task Commits

Each task was committed atomically:

1. **Task 1: ApprovalManager with Redis state and timeout-to-reject** - `16b0285` (feat)
2. **Task 2: Unit tests for ApprovalManager** - `44cdb16` (test)

## Files Created/Modified

- `src/trading/alerts/approval.py` - ApprovalManager class with request_approval, resolve, get_pending, recover_expired (280 lines)
- `tests/test_approval_manager.py` - 10 unit tests covering all approval lifecycle paths (328 lines)
- `src/trading/agents/state.py` - PipelineState extended with approval_status and approval_id fields
- `src/trading/agents/pipeline.py` - run_pipeline initial_state includes new approval fields

## Decisions Made

- Used `asyncio.wait({future}, timeout=...)` instead of `asyncio.wait_for(future, ...)` because it allows checking `future in done` cleanly without catching TimeoutError, and pairs well with the background listener_task cancellation pattern
- Redis key TTL set to `timeout + 3600` (1 hour after timeout) so the dashboard can display recently-timed-out approvals for visibility
- Used `scan_iter(match="approval:*")` (not KEYS) for get_pending -- production-safe Redis enumeration matching existing project patterns (DashboardPublisher uses SCAN)
- `_listen_for_resolution` spawned as `asyncio.create_task` (not ensure_future) matching project convention from Phase 1

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated pipeline.py initial_state for new PipelineState fields**
- **Found during:** Task 1
- **Issue:** Adding approval_status and approval_id to PipelineState TypedDict requires the initial_state dict in run_pipeline to include these fields, otherwise LangGraph state would be incomplete
- **Fix:** Added `"approval_status": ""` and `"approval_id": ""` to initial_state in pipeline.py
- **Files modified:** src/trading/agents/pipeline.py
- **Verification:** All 84 existing agent tests pass
- **Committed in:** 16b0285 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for correctness -- PipelineState fields must match initial_state. No scope creep.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ApprovalManager ready for integration with pipeline approval gate (Plan 03)
- resolve() method ready for dashboard REST endpoint (Plan 04) and Slack button handler (Plan 05)
- recover_expired() ready to be called in TradingApp startup()
- PipelineState approval fields ready for approval gate node to set

---
*Phase: 08-alerts-autonomy*
*Completed: 2026-04-05*
