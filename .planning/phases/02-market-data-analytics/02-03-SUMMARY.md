---
phase: 02-market-data-analytics
plan: 03
subsystem: analytics
tags: [iv-rank, iv-percentile, implied-volatility, ib-historical-data, rate-limiting, timescaledb, caching]

# Dependency graph
requires:
  - phase: 02-01
    provides: IVHistory ORM model, IVData Pydantic model, TimescaleDB schema
provides:
  - IVHistoryManager for fetching/storing historical IV data from IB
  - IVEngine for computing IV rank and percentile with caching
  - Rate-limited IB historical data bootstrapping for watchlists
affects: [02-05, 05-scanner-agent, strategy-selection]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "IB rate limiter with sliding window (55/10min) and min spacing (2.5s)"
    - "INSERT ON CONFLICT DO NOTHING for idempotent time-series upserts"
    - "Static methods for pure computation enabling unit testing without DB"
    - "In-memory cache with configurable TTL refresh interval"

key-files:
  created:
    - src/trading/analytics/iv_history.py
    - src/trading/analytics/iv_engine.py
  modified:
    - src/trading/analytics/__init__.py

key-decisions:
  - "Conservative IB rate limits: 55/window (vs 60 max), 2.5s spacing (vs 2s min)"
  - "Minimum 20 data points required for IV rank/percentile; returns None below threshold"
  - "Sequential watchlist bootstrap (not concurrent) to respect IB pacing"
  - "IV rank = range position; IV percentile = days-below ratio -- distinct metrics"
  - "Used timezone-aware datetime.now(tz=timezone.utc) instead of deprecated utcnow()"

patterns-established:
  - "IB rate limiter: sliding window with monotonic timestamps and min spacing"
  - "Cold start safety: return None (not 0 or 50) for insufficient data"
  - "Cache pattern: dict + timestamps with configurable refresh interval"

# Metrics
duration: 3min
completed: 2026-04-02
---

# Phase 2 Plan 3: IV Analytics Engine Summary

**IVHistoryManager for rate-limited IB historical IV fetching/storage and IVEngine for IV rank/percentile computation with 15-min cached refresh**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-02T18:16:22Z
- **Completed:** 2026-04-02T18:18:53Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- IVHistoryManager fetches daily IV from IB with sliding-window rate limiter (55 req/10min, 2.5s spacing)
- Historical IV stored in TimescaleDB with ON CONFLICT DO NOTHING for idempotent upserts
- IVEngine computes IV rank (range position) and percentile (days below) with 20-point minimum threshold
- Cold start returns None for both metrics -- never misleading numeric defaults
- Configurable cache refresh interval (default 15 minutes) for production performance

## Task Commits

Each task was committed atomically:

1. **Task 1: IVHistoryManager - IB historical data fetching with rate limiting and storage** - `ee91ed5` (feat)
2. **Task 2: IVEngine - IV rank/percentile computation with caching** - `4139818` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified
- `src/trading/analytics/iv_history.py` - IVHistoryManager: IB historical IV fetching, rate limiting, TimescaleDB storage, watchlist bootstrap
- `src/trading/analytics/iv_engine.py` - IVEngine: IV rank/percentile computation with static methods and caching
- `src/trading/analytics/__init__.py` - Package exports for IVEngine and IVHistoryManager

## Decisions Made
- Conservative IB rate limits (55/10min window, 2.5s spacing) provide safety margin against IB disconnects
- 20 data points minimum (~1 month of trading days) for meaningful IV rank/percentile calculations
- Sequential watchlist bootstrap ensures IB pacing compliance; asyncio.gather only used for DB reads in compute_batch
- Used timezone-aware datetime (datetime.now(tz=timezone.utc)) instead of deprecated datetime.utcnow()
- IV rank and IV percentile are distinct metrics: rank is range position, percentile is days-below proportion

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- IV analytics engine complete; IVHistoryManager and IVEngine ready for integration
- Scanner agent (Phase 5) can use IVEngine.compute() to filter opportunities by IV rank/percentile
- MarketDataManager (02-05) will wire IVHistoryManager for periodic snapshot_current_iv calls
- No blockers for remaining Phase 2 plans

---
*Phase: 02-market-data-analytics*
*Completed: 2026-04-02*
