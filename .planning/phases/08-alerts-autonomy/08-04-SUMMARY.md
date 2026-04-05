---
phase: 08-alerts-autonomy
plan: 04
subsystem: dashboard-approvals
tags: [fastapi, rest, websocket, nextjs, zustand, approval-ui, pydantic]

dependency_graph:
  requires:
    - phase: 08-02
      provides: ApprovalManager with Redis state, resolve(), get_pending()
    - phase: 08-03
      provides: Pipeline approval gate routing trades to ApprovalManager
    - phase: 07-01
      provides: FastAPI app factory, RedisBridge, ChannelManager, WebSocket endpoint
    - phase: 07-02
      provides: Dashboard WebSocket client singleton, Zustand store pattern, nav-sidebar
  provides:
    - REST endpoints GET /api/approvals/pending and POST /api/approvals/{id}/resolve
    - Dashboard /approvals page with approval cards, trade context, timeout countdown
    - Zustand approvals-store with WebSocket real-time updates
    - Navigation sidebar with Approvals link and pending count badge
  affects:
    - 08-05 (Slack interactive buttons provide alternate resolution channel)

tech_stack:
  added: []
  patterns:
    - "Approval REST endpoints delegate to ApprovalManager stored on app.state"
    - "WebSocket bridge maps alerts:approval_request and alerts:approval_resolved to 'approvals' topic"
    - "Zustand store re-fetches pending list on any WebSocket approval event (simplest approach)"
    - "ApprovalCard uses setInterval countdown timer with automatic cleanup"

key_files:
  created:
    - src/trading/dashboard/routes/approvals.py
    - dashboard/src/app/approvals/page.tsx
    - dashboard/src/components/approvals/approval-card.tsx
    - dashboard/src/components/approvals/trade-context.tsx
    - dashboard/src/stores/approvals-store.ts
  modified:
    - src/trading/dashboard/models.py
    - src/trading/dashboard/server.py
    - src/trading/dashboard/ws/bridge.py
    - dashboard/src/lib/api.ts
    - dashboard/src/lib/ws-client.ts
    - dashboard/src/types/index.ts
    - dashboard/src/components/nav-sidebar.tsx

decisions:
  - id: "08-04-01"
    decision: "Zustand store re-fetches full pending list on any WebSocket approval event"
    rationale: "Simplest approach; avoids complex partial state management for approval_request and approval_resolved events. Approval queue is small so full re-fetch is cheap."
  - id: "08-04-02"
    decision: "Both alerts:approval_request and alerts:approval_resolved map to single 'approvals' WebSocket topic"
    rationale: "Frontend only needs to know 'something changed' and re-fetches; no need for separate channels."
  - id: "08-04-03"
    decision: "ApprovalManager created in dashboard lifespan with mode-specific timeout"
    rationale: "Dashboard server needs its own ApprovalManager instance for resolve() calls; timeout derived from settings.auto_execute paper/live thresholds."
  - id: "08-04-04"
    decision: "ApprovalContext parsing with try/except fallback to raw dict"
    rationale: "Gracefully handles approvals with incomplete or non-standard context fields without crashing the endpoint."

metrics:
  duration: 7min
  completed: 2026-04-05
  tasks_completed: 2
  tasks_total: 2
---

# Phase 08 Plan 04: Dashboard Approval UI Summary

REST endpoints for listing/resolving trade approvals, Next.js approval queue page with card components showing trade context and countdown timer, Zustand store with WebSocket real-time updates, and navigation integration with pending count badge.

## What Was Built

### Backend (Task 1)
- **Pydantic models**: ApprovalContext, ApprovalResponse, ApprovalResolveRequest, ApprovalResolveResponse added to dashboard models
- **GET /api/approvals/pending**: Returns pending approvals from Redis via ApprovalManager.get_pending(), parses context JSON into structured ApprovalContext, sorts by requested_at ascending
- **POST /api/approvals/{id}/resolve**: Accepts "approved"/"rejected" decision, delegates to ApprovalManager.resolve(), returns 503 if manager unavailable
- **ApprovalManager on app.state**: Created in dashboard lifespan with mode-specific timeout (paper vs live)
- **WebSocket bridge**: Added alerts:approval_request and alerts:approval_resolved to CHANNELS, both mapped to "approvals" topic
- **Channel snapshot**: Approvals channel returns pending approvals list via scan_iter on subscribe

### Frontend (Task 2)
- **TypeScript types**: ApprovalContext and Approval interfaces in types/index.ts
- **API functions**: getPendingApprovals() and resolveApproval() in api.ts using existing fetchApi pattern
- **Zustand store**: approvals-store.ts with fetchApprovals, resolveApproval, updateFromWs actions; re-fetches on WebSocket events
- **TradeContext component**: Grid layout showing symbol, strategy, max loss/profit, delta/theta/vega impact; red highlight on max_loss > $1000
- **ApprovalCard component**: Card with trade context, live countdown timer (setInterval), approve/reject buttons with disable-on-click, status badges for resolved states
- **Approvals page**: Client component with fetch on mount, WebSocket subscription to "approvals" channel, empty state message, error display
- **Navigation update**: Approvals link added after Trades, pending count badge displayed when > 0
- **WebSocket client**: Updated to route "approvals" channel snapshots and updates to approvals store

## Deviations from Plan

None -- plan executed exactly as written.

## Key Integration Points

1. **Routes -> ApprovalManager**: REST handlers call `approval_manager.get_pending()` and `approval_manager.resolve()` from app.state
2. **WebSocket -> Store**: RedisBridge forwards approval pub/sub events to "approvals" topic; ws-client routes to useApprovalsStore.updateFromWs()
3. **Card -> REST**: ApprovalCard approve/reject buttons trigger `resolveApproval()` API call which POST to /api/approvals/{id}/resolve

## Verification Results

| Check | Result |
|-------|--------|
| Approvals router imports | OK |
| Approval models import | OK |
| Routes registered in app | /api/approvals/pending, /api/approvals/{id}/resolve |
| RedisBridge channels | alerts:approval_request, alerts:approval_resolved present |
| TypeScript compilation | 0 errors |
| File min_lines | All exceeded (routes: 140/40, page: 71/30, card: 140/50, store: 52/30) |
