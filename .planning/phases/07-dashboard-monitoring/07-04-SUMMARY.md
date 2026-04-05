---
phase: 07-dashboard-monitoring
plan: 04
subsystem: dashboard
tags: [fastapi, nextjs, greeks, trades, reasoning-chain, zustand, redis, sqlalchemy]

# Dependency graph
requires:
  - phase: 07-01
    provides: FastAPI app factory, WebSocket bridge, Redis pub/sub, dashboard models
  - phase: 07-02
    provides: Next.js shell, shadcn/ui components, Zustand stores, api.ts helpers
  - phase: 05-05
    provides: Pipeline with run_id, AgentDecisionLog with reasoning data
  - phase: 04-04
    provides: Order model with proposal_id field
provides:
  - Portfolio Greeks REST endpoint aggregating from Redis
  - Per-position Greeks breakdown endpoint
  - Paginated trade history endpoint with reasoning chain joins
  - Single trade detail endpoint
  - Greeks display page with 4 metric cards and color thresholds
  - Trade history page with expandable reasoning chains
  - Fixed proposal_id/run_id linkage for reasoning chain data integrity
affects: [07-06, future-analytics]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Redis SCAN for Greeks aggregation (not KEYS, production safety)"
    - "Order.proposal_id == AgentDecisionLog.run_id join for reasoning chains"
    - "10-second polling fallback for WebSocket data freshness"
    - "Expandable table rows with local state for detail views"

key-files:
  created:
    - src/trading/dashboard/routes/greeks.py
    - src/trading/dashboard/routes/trades.py
    - dashboard/src/app/greeks/page.tsx
    - dashboard/src/components/greeks/greeks-display.tsx
    - dashboard/src/app/trades/page.tsx
    - dashboard/src/components/trades/trade-history.tsx
    - dashboard/src/components/trades/reasoning-chain.tsx
  modified:
    - src/trading/agents/executor_agent.py
    - src/trading/agents/pipeline.py
    - dashboard/src/lib/api.ts

key-decisions:
  - "Fixed proposal_id/run_id linkage in executor agent so Order-to-AgentDecisionLog join returns data"
  - "Greeks thresholds hardcoded (delta>500=yellow, >1000=red) matching risk_limits patterns"
  - "Trades endpoint uses per-order reasoning chain query (N+1) for simplicity at current scale"
  - "api.ts getTradeHistory updated to return {trades, total} envelope for pagination metadata"

patterns-established:
  - "Expandable table rows: local expandedRow state with conditional rendering"
  - "Polling fallback: useEffect with setInterval + cleanup for data freshness"
  - "Color-coded agent badges: scanner=blue, strategist=purple, risk_manager=orange, executor=green"

# Metrics
duration: 6min
completed: 2026-04-05
---

# Phase 7 Plan 4: Greeks Display and Trade History Summary

**Portfolio Greeks display with 4 color-coded metric cards, paginated trade history with expandable agent reasoning chains, and fixed proposal_id/run_id linkage enabling the Order-to-AgentDecisionLog join**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-05T01:29:42Z
- **Completed:** 2026-04-05T01:35:46Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- Fixed critical proposal_id/run_id linkage: ExecutorDeps.run_id flows from PipelineState through submit_trade to TradeProposal.proposal_id, enabling the join that populates reasoning chains
- Built 2 REST endpoints (GET /api/greeks, GET /api/trades/history) serving real-time Greeks from Redis and paginated trade history from PostgreSQL
- Created Greeks page with 4 metric cards (delta, gamma, theta, vega) with green/yellow/red color thresholds and 10-second polling
- Created Trades page with expandable rows showing full pipeline reasoning chains (scanner -> strategist -> risk_manager -> executor) with agent badges, reasoning text, output summaries, and duration

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix proposal_id/run_id linkage and build Greeks/trade history REST endpoints** - `4d4d83e` (feat)
2. **Task 2: Greeks display and trade history frontend components** - `4aedb4e` (feat)

## Files Created/Modified
- `src/trading/agents/executor_agent.py` - Added run_id field to ExecutorDeps, pass as proposal_id in submit_trade
- `src/trading/agents/pipeline.py` - Pass state run_id into ExecutorDeps in _executor_node
- `src/trading/dashboard/routes/greeks.py` - Portfolio and per-position Greeks from Redis SCAN
- `src/trading/dashboard/routes/trades.py` - Paginated trade history with reasoning chain join
- `dashboard/src/app/greeks/page.tsx` - Greeks page with polling
- `dashboard/src/components/greeks/greeks-display.tsx` - 4 Greek metric cards with color indicators
- `dashboard/src/app/trades/page.tsx` - Trade history page with pagination state
- `dashboard/src/components/trades/trade-history.tsx` - Paginated table with expandable rows
- `dashboard/src/components/trades/reasoning-chain.tsx` - Agent reasoning timeline with badges
- `dashboard/src/lib/api.ts` - Updated getTradeHistory to use /api/trades/history and {trades, total} response

## Decisions Made
- Fixed proposal_id/run_id linkage in executor agent so Order-to-AgentDecisionLog join returns data (this was the critical enabler for reasoning chain display)
- Greeks thresholds hardcoded (delta>500=yellow, >1000=red) matching risk_limits patterns -- can be made configurable later
- Trades endpoint uses per-order reasoning chain query (N+1 on AgentDecisionLog) which is fine at current scale (50 trades per page max)
- Updated api.ts getTradeHistory return type to {trades, total} envelope for pagination metadata

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Import get_db_session from deps module**
- **Found during:** Task 1 (trades route creation)
- **Issue:** trades.py initially imported get_db_session from server.py (per plan), but server.py had been refactored in 07-03 to re-export from deps.py. Direct import from server.py would create circular import.
- **Fix:** Changed import to `from trading.dashboard.deps import get_db_session`
- **Files modified:** src/trading/dashboard/routes/trades.py
- **Verification:** Routes registered correctly in create_app()
- **Committed in:** 4d4d83e (Task 1 commit)

**2. [Rule 3 - Blocking] Update api.ts trade history path and return type**
- **Found during:** Task 2 (frontend integration)
- **Issue:** api.ts had getTradeHistory pointing to `/api/trades` (old path) returning `TradeHistoryItem[]`, but backend serves `/api/trades/history` returning `{trades, total}` envelope
- **Fix:** Updated path and return type to match actual backend API
- **Files modified:** dashboard/src/lib/api.ts
- **Verification:** pnpm build succeeds, types match
- **Committed in:** 4aedb4e (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both auto-fixes necessary for correct imports and API contract alignment. No scope creep.

## Issues Encountered
- Server.py had already been modified by prior plans (07-03, 07-05) which pre-emptively imported greeks_router and trades_router, so server.py edits were no-ops

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Greeks and trade history pages fully functional when backend serves data
- WebSocket portfolio_greeks channel already wired in 07-01 for push updates
- Reasoning chain join ready for production once pipeline runs stamp proposal_id correctly

---
*Phase: 07-dashboard-monitoring*
*Completed: 2026-04-05*
