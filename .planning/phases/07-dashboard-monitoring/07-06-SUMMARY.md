---
phase: 07-dashboard-monitoring
plan: 06
subsystem: dashboard-scenarios
tags: [black-scholes, scipy, scenario-analysis, react, fastapi, what-if]

dependency_graph:
  requires: ["07-03"]
  provides:
    - "Black-Scholes pricing engine using scipy.stats.norm.cdf"
    - "scenario_pnl function for portfolio-wide what-if analysis"
    - "POST /api/scenarios endpoint with contract detail resolution from Redis/OCC"
    - "Scenario analysis page with interactive form, presets, and results display"
  affects: []

tech_stack:
  added:
    - "scipy>=1.12.0"
    - "numpy>=1.26.0"
  patterns:
    - "Black-Scholes standard formula with intrinsic value fallback at expiration"
    - "Multi-strategy contract resolution: Redis cache -> OCC symbol parsing -> inline fields"
    - "Preset scenario buttons for common what-if analyses (crash, rally, IV crush, theta)"
    - "Side-by-side form/results layout with summary cards and per-position breakdown"

file_tracking:
  key_files:
    created:
      - src/trading/dashboard/scenario_engine.py
      - src/trading/dashboard/routes/scenarios.py
      - dashboard/src/app/scenarios/page.tsx
      - dashboard/src/components/scenarios/scenario-form.tsx
      - dashboard/src/components/scenarios/scenario-results.tsx
    modified:
      - pyproject.toml
      - src/trading/dashboard/server.py
      - dashboard/src/types/index.ts
      - tests/test_dashboard.py

decisions:
  - id: "07-06-01"
    description: "scipy.stats.norm.cdf for Black-Scholes CDF (standard, well-tested implementation)"
  - id: "07-06-02"
    description: "Default IV of 0.25 (25%) when implied volatility unavailable from Redis or position data"
  - id: "07-06-03"
    description: "OCC symbol parsing as fallback for contract detail resolution when Redis cache misses"
  - id: "07-06-04"
    description: "ScenarioPositionResult typed interface instead of unknown[] for per-position results"

metrics:
  duration: "8min"
  completed: "2026-04-05"
  tests_added: 17
  tests_total: 38
---

# Phase 7 Plan 6: P&L Scenario Analysis Summary

Black-Scholes pricing engine with scipy.stats.norm for what-if portfolio analysis via interactive dashboard

## What Was Built

### Backend: Scenario Engine and REST Endpoint

1. **Black-Scholes Pricing Engine** (`scenario_engine.py`):
   - `black_scholes_price(S, K, T, r, sigma, option_type)` -- standard BS formula using scipy.stats.norm.cdf
   - Handles edge cases: T <= 0 returns intrinsic value, sigma <= 0 returns discounted intrinsic
   - `scenario_pnl(positions, ...)` re-prices all positions under hypothetical conditions
   - Returns current_value, scenario_value, pnl, pnl_percent, per_position breakdown, skipped list

2. **Scenarios REST Endpoint** (`routes/scenarios.py`):
   - POST /api/scenarios accepts underlying_change_pct, iv_change_pct, days_forward, risk_free_rate
   - Multi-strategy contract detail resolution for each option position:
     a. Redis contract cache (contractcache:{con_id})
     b. OCC symbol parsing via regex
     c. Inline position fields
   - Fetches underlying prices from mktdata:latest:quote:* Redis keys
   - Fetches implied volatility from mktdata:latest:greeks:* Redis keys
   - Skips non-option positions and unresolvable contracts with explanatory messages

3. **Dependencies**: Added scipy>=1.12.0 and numpy>=1.26.0 to pyproject.toml

### Frontend: Scenario Analysis Page

1. **ScenarioForm** (`scenario-form.tsx`):
   - Range sliders for underlying change (-30% to +30%), IV change (-50% to +100%), days forward (0-60)
   - Four preset buttons: Market Crash (-10%), Rally (+5%), IV Crush (-30%), 1 Week Theta
   - Loading state during calculation

2. **ScenarioResults** (`scenario-results.tsx`):
   - Four summary cards: Current Value, Scenario Value, P&L Change, P&L Change %
   - Per-position breakdown table with symbol, type, strike, DTE, quantity, current/scenario values, P&L
   - Skipped positions section with explanatory reasons
   - Color-coded P&L values (green positive, red negative)

3. **Scenarios Page** (`app/scenarios/page.tsx`):
   - Side-by-side layout: form on left, results on right
   - Calls POST /api/scenarios via fetchApi helper

### Test Suite

- 8 Black-Scholes pricing tests: ATM call/put ranges, ITM/OTM at expiration, deep ITM, zero vol
- 9 scenario_pnl tests: call/put directional, empty positions, theta decay, IV increase, short positions, P&L percent, per-position breakdown, invalid position skipping
- Total dashboard tests: 38 (all passing)

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| 07-06-01 | scipy.stats.norm.cdf for BS CDF | Standard, well-tested implementation; consistent with py_vollib approach |
| 07-06-02 | Default IV 0.25 when unavailable | 25% is a reasonable middle-ground for equity options; better than failing |
| 07-06-03 | OCC symbol parsing as fallback | Allows scenario analysis for positions with partial metadata in Redis |
| 07-06-04 | ScenarioPositionResult typed interface | TypeScript build required proper typing; unknown[] caused filter type errors |

## Verification Results

- `black_scholes_price(100, 100, 0.25, 0.05, 0.2, 'C')` returns ~5.09 (within 3-7 range)
- `black_scholes_price(105, 100, 0, 0.05, 0.2, 'C')` returns exactly 5.0 (intrinsic)
- `scenario_pnl` with +5% underlying returns positive P&L for long calls
- Scenarios route registered at /api/scenarios
- All 38 pytest tests pass
- Next.js build compiles with /scenarios route
