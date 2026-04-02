---
plan: 02-04
phase: 02-market-data-analytics
status: complete
completed_at: 2026-04-02T18:21:00Z
duration_minutes: 4
commits:
  - e5dfda3: "feat(02-04): EarningsCalendar with Finnhub integration and daily caching"
  - 3614d76: "test(02-04): earnings calendar unit tests"
subsystem: market-data
tags: [finnhub, earnings, iv-expansion, api-integration, caching]
dependency_graph:
  requires: [02-01]
  provides: [earnings-calendar, earnings-flags]
  affects: [02-05, 05-scanner-agent]
tech_stack:
  added: [finnhub-python]
  patterns: [sdk-with-httpx-fallback, pg-upsert, in-memory-cache, executor-for-sync-sdk]
key_files:
  created:
    - src/trading/analytics/earnings.py
    - tests/test_earnings.py
  modified:
    - pyproject.toml
    - src/trading/analytics/__init__.py
    - uv.lock
decisions:
  - "finnhub-python SDK works on Python 3.14 -- no httpx fallback needed at install time"
  - "httpx fallback retained in code for runtime resilience if SDK call fails"
  - "Individual entry parsing errors logged and skipped (partial results preferred over total failure)"
---

# Phase 2 Plan 4: Earnings Calendar Summary

EarningsCalendar service integrating Finnhub API for earnings date lookups with upsert storage, in-memory caching, and configurable lookout window flags.

## What Was Built

### EarningsCalendar Service (`src/trading/analytics/earnings.py`)

Core service with six methods covering the full earnings data lifecycle:

- **fetch_earnings**: Calls Finnhub API via SDK (sync, run in executor) with httpx async fallback. Returns raw earnings dicts. Gracefully handles missing API key and all error conditions.
- **store_earnings**: Upserts earnings data into `earnings_events` table using PostgreSQL `ON CONFLICT DO UPDATE`. Updates eps_estimate, revenue_estimate, hour, and fetched_at on conflict.
- **refresh_watchlist**: Batch fetches and stores for a list of symbols. Looks ahead `lookout_days * 4` to pre-populate data. Clears cache and updates last-refresh timestamp.
- **get_earnings_flags**: Queries DB for earnings within the lookout window, builds EarningsFlag Pydantic models with computed `days_until`, caches per-symbol.
- **get_earnings_flag**: Single-symbol convenience wrapper returning first upcoming flag or None.
- **needs_refresh**: Returns True if no refresh has occurred or last refresh was >24 hours ago.

### Dependency Addition

Added `finnhub-python>=2.4.27` to pyproject.toml. The SDK installed cleanly on Python 3.14.3 despite pre-plan concerns about compatibility.

### Unit Tests (`tests/test_earnings.py`)

9 tests covering:
- EarningsFlag model creation with all fields and optional-only fields
- JSON serialization roundtrip
- needs_refresh logic: no prior refresh, stale (>24h), fresh (<24h), boundary
- fetch_earnings graceful empty return when API key is missing

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added per-entry error handling in store_earnings**
- **Found during:** Task 1 implementation
- **Issue:** Plan showed bare upsert loop without handling malformed entries
- **Fix:** Added try/except for KeyError and ValueError around each entry parse, logging warnings for bad entries while continuing to process remaining entries
- **Files modified:** src/trading/analytics/earnings.py

**2. [Rule 3 - Blocking] Analytics __init__.py already updated by parallel plan 02-03**
- **Found during:** Task 1 commit
- **Issue:** The 02-03 parallel executor pre-emptively added EarningsCalendar to the analytics __init__.py exports
- **Fix:** No action needed -- the file was already correct at HEAD
- **Files modified:** None (already committed)

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| finnhub-python SDK works on Python 3.14 | Installed cleanly; no need to fall back to httpx-only at install time |
| Retained httpx fallback in code | Runtime resilience if SDK import fails in other environments |
| Per-entry error isolation in store_earnings | Partial results preferred over total failure on one bad entry |

## Next Phase Readiness

Plan 02-04 delivers the earnings calendar service that Phase 5 scanner agents will consume. The service is ready for integration once a Finnhub API key is configured via `FINNHUB_API_KEY` environment variable. Without the key, all methods degrade gracefully to empty results.
