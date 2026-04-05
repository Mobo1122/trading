---
phase: 07-dashboard-monitoring
plan: 05
subsystem: dashboard-health
tags: [fastapi, health-check, websocket, react, zustand, agent-visibility]

dependency_graph:
  requires: ["07-01", "07-02"]
  provides:
    - "GET /api/health/status endpoint with IB/DB/Redis/freshness/agent-last-seen"
    - "Health monitoring page with connection badges, agent activity, data freshness"
    - "Shared deps module for FastAPI dependency injection (breaking circular imports)"
  affects: ["07-06"]

tech_stack:
  added: []
  patterns:
    - "Shared deps module for FastAPI DI to avoid circular imports between server and routes"
    - "Per-agent last-seen via SQL GROUP BY max(timestamp) on AgentDecisionLog"
    - "REST polling (10s) merged with WebSocket store updates for health status"
    - "Data freshness computed from Redis SCAN of mktdata:latest:quote:* timestamps"

file_tracking:
  key_files:
    created:
      - src/trading/dashboard/routes/health.py
      - src/trading/dashboard/deps.py
      - dashboard/src/app/health/page.tsx
      - dashboard/src/components/health/health-panel.tsx
      - dashboard/src/components/health/data-freshness.tsx
    modified:
      - src/trading/dashboard/server.py
      - dashboard/src/lib/api.ts

decisions:
  - id: "07-05-01"
    decision: "Extract get_db_session to deps.py to break circular import"
    reasoning: "health router imports get_db_session, server.py imports health router -- circular. deps.py breaks the cycle with re-export for backward compat."
  - id: "07-05-02"
    decision: "Agent last-seen thresholds: 10min stale, 1hr inactive"
    reasoning: "Pipeline runs every few minutes; 10min without activity is a warning, 1hr is a problem."

metrics:
  duration: "5min"
  completed: "2026-04-05"
---

# Phase 07 Plan 05: Health Monitoring Panel Summary

Health monitoring panel with connection status, agent visibility, and data stream freshness -- REST endpoint aggregates Redis, DB, and AgentDecisionLog checks into a single HealthStatus response; frontend renders badges, agent activity, and freshness table.

## What Was Built

### Backend: Health REST Endpoint (Task 1)

**`src/trading/dashboard/routes/health.py`** -- APIRouter with `GET /api/health/status`:

- **Redis check**: `await redis.ping()` with try/except.
- **DB check**: `SELECT 1` via async session.
- **IB check**: Reads `dashboard:ib_status` from Redis (published by DashboardPublisher).
- **Data freshness**: SCAN `mktdata:latest:quote:*`, reads timestamp field, computes staleness per symbol.
- **Pipeline status**: Reads `dashboard:pipeline_status` from Redis.
- **Heartbeat**: Reads `dashboard:heartbeat` from Redis.
- **Per-agent last-seen**: Queries AgentDecisionLog `max(timestamp) GROUP BY agent_name`.

Returns a `HealthStatus` Pydantic model with all fields.

**`src/trading/dashboard/deps.py`** -- Shared FastAPI dependency for `get_db_session`, re-exported from `server.py` for backward compatibility. Breaks the circular import between server.py and route modules.

### Frontend: Health Monitoring Page (Task 2)

**`dashboard/src/components/health/health-panel.tsx`** -- Connection status cards with colored badges for IB/DB/Redis, pipeline status badge, heartbeat relative time, and per-agent last-seen indicators with color-coded freshness (green < 10min, yellow < 1hr, red > 1hr).

**`dashboard/src/components/health/data-freshness.tsx`** -- Data stream freshness table with Symbol, Last Update, and Status (Fresh < 30s, Stale < 120s, Dead > 120s). Stale/dead rows highlighted with warning background.

**`dashboard/src/app/health/page.tsx`** -- Health page fetching initial data from REST, polling every 10s, merging WebSocket store updates. Renders HealthPanel and DataFreshness components.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Circular import between server.py and health route**

- **Found during:** Task 1
- **Issue:** health.py imports `get_db_session` from server.py, but server.py imports health router -- circular import at module load time.
- **Fix:** Extracted `get_db_session` to new `deps.py` module. server.py re-exports it for backward compatibility.
- **Files created:** `src/trading/dashboard/deps.py`
- **Commit:** 954c2fb

## Verification Results

- Health status route registered at `/api/health/status`
- Simple `/api/health` probe endpoint preserved
- HealthStatus model contains all 7 required fields
- `pnpm build` compiles without errors
- All key_link patterns matched in source
- Line counts exceed minimums: health.py (235), health-panel.tsx (159), data-freshness.tsx (95)

## Next Phase Readiness

Plan 07-05 is complete. The health endpoint and frontend page are ready for integration with the full dashboard. The `deps.py` module provides a clean pattern for other routes that need database sessions without circular imports.
