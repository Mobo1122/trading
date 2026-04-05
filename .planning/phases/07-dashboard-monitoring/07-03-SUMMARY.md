---
phase: 07-dashboard-monitoring
plan: 03
subsystem: dashboard
tags: [fastapi, next.js, zustand, websocket, positions, pnl, rest-api, pytest]

# Dependency graph
requires:
  - phase: 07-01
    provides: "FastAPI server, WebSocket manager, Redis bridge, dashboard publisher"
  - phase: 07-02
    provides: "Next.js shell, shadcn/ui components, Zustand stores, API client"
provides:
  - "GET /api/positions endpoint with real-time price enrichment from Redis"
  - "GET /api/portfolio endpoint with aggregated P&L summary"
  - "Positions page with sortable table and portfolio summary cards"
  - "21 unit tests for ChannelManager, RedisBridge, and REST endpoints"
affects: [07-04, 07-05, 07-06]

# Tech tracking
tech-stack:
  added: [httpx]
  patterns:
    - "REST endpoint reads Redis-cached data published by DashboardPublisher"
    - "Options multiplier 100x for P&L calculation vs stocks at 1x"
    - "Zustand store hydrated from REST on mount, then updated via WebSocket"

key-files:
  created:
    - src/trading/dashboard/routes/positions.py
    - dashboard/src/app/positions/page.tsx
    - dashboard/src/components/positions/positions-table.tsx
    - dashboard/src/components/positions/portfolio-summary.tsx
    - tests/test_dashboard.py
  modified:
    - src/trading/dashboard/server.py

key-decisions:
  - "P&L multiplier: 100x for options (OPT), 1x for stocks (STK) -- standard contract sizing"
  - "Price source: last price preferred, fallback to bid/ask midpoint"
  - "Portfolio /api/portfolio calls /api/positions internally to aggregate -- single source of truth"
  - "Net liquidation = market_value + unrealized_pnl + realized_pnl (additive formula)"

patterns-established:
  - "FastAPI route modules registered via app.include_router in create_app()"
  - "REST tests use httpx.AsyncClient with ASGITransport for async endpoint testing"
  - "Frontend pages fetch initial data on mount, then rely on WebSocket for updates"

# Metrics
duration: 6min
completed: 2026-04-05
---

# Phase 7 Plan 3: Positions Display with Real-Time P&L Summary

**REST endpoints for positions/portfolio with Redis price enrichment, sortable positions table with color-coded P&L, and 21 dashboard unit tests**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-05T01:29:04Z
- **Completed:** 2026-04-05T01:34:35Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments
- GET /api/positions returns positions enriched with real-time prices from Redis mktdata cache, computing per-position unrealized P&L with correct option multiplier
- GET /api/portfolio aggregates market value, unrealized/realized P&L, and net liquidation across all positions
- Positions page with PortfolioSummary (4 metric cards) and PositionsTable (8 sortable columns with P&L color coding)
- 21 tests covering ChannelManager lifecycle, RedisBridge channel mapping, and REST endpoint responses with mock Redis

## Task Commits

Each task was committed atomically:

1. **Task 1: Positions REST endpoints and server wiring** - `15bcca4` (feat)
2. **Task 2: Positions frontend components and dashboard tests** - `a2fd1c0` (feat)

## Files Created/Modified
- `src/trading/dashboard/routes/positions.py` - GET /api/positions and GET /api/portfolio endpoints with Redis price lookup and P&L math
- `src/trading/dashboard/server.py` - Wired positions_router via include_router
- `dashboard/src/components/positions/portfolio-summary.tsx` - 4 metric cards: market value, unrealized/realized P&L, net liquidation
- `dashboard/src/components/positions/positions-table.tsx` - Sortable table with Symbol, Type, Qty, Avg Cost, Current Price, Market Value, P&L ($), P&L (%)
- `dashboard/src/app/positions/page.tsx` - Positions page with initial REST fetch and store hydration
- `tests/test_dashboard.py` - 21 tests for ChannelManager, RedisBridge, REST endpoints

## Decisions Made
- P&L multiplier: 100x for options (OPT sec_type), 1x for stocks (STK) -- standard options contract sizing
- Price source priority: last price preferred, fallback to bid/ask midpoint if last unavailable
- Portfolio endpoint internally calls get_positions to aggregate -- keeps calculation in one place
- Net liquidation formula: total_market_value + total_unrealized_pnl + total_realized_pnl
- Test strategy: httpx.AsyncClient with ASGITransport for async FastAPI endpoint testing (no real Redis/DB)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Positions page renders correctly, ready for WebSocket real-time updates
- REST endpoints available for any frontend component to fetch snapshot data
- Test infrastructure established for adding more dashboard endpoint tests

---
*Phase: 07-dashboard-monitoring*
*Completed: 2026-04-05*
