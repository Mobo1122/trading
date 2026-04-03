---
phase: "03-risk-engine"
plan: "01"
subsystem: "risk"
tags: ["pydantic", "sqlalchemy", "alembic", "risk-models", "config"]
dependency_graph:
  requires: ["01-01", "01-02", "02-01"]
  provides: ["risk-domain-models", "risk-config", "risk-schema"]
  affects: ["03-02", "03-03", "03-04", "03-05", "03-06"]
tech_stack:
  added: []
  patterns: ["paper-live-config-separation", "field-validator-rejection", "enum-based-rule-tracking"]
key_files:
  created:
    - "src/trading/risk/__init__.py"
    - "src/trading/risk/models.py"
    - "src/trading/risk/config.py"
    - "alembic/versions/003_risk_engine_schema.py"
  modified:
    - "src/trading/config.py"
    - "config/default.yml"
    - "src/trading/db/models.py"
decisions:
  - id: "03-01-01"
    decision: "timezone-aware datetime.now(timezone.utc) for RiskDecision.evaluated_at default factory"
    rationale: "Follows project convention established in Phase 2 (no utcnow)"
  - id: "03-01-02"
    decision: "risk_decisions and circuit_breaker_state are regular tables, not hypertables"
    rationale: "Risk decisions are low-frequency events; not time-series workload"
  - id: "03-01-03"
    decision: "Paper limits 2x live limits in YAML defaults"
    rationale: "Paper mode is for testing; relaxed limits reduce friction while still validating logic"
metrics:
  duration: "5min"
  completed: "2026-04-03"
---

# Phase 03 Plan 01: Risk Domain Models Summary

JWT-free risk foundation: ViolatedRule enum (16 rejection reasons), TradeProposal/RiskDecision Pydantic models with Field validation, paper/live RiskLimitsConfig loaded from YAML, ORM models for risk_decisions and circuit_breaker_state tables, Alembic migration 003.

## What Was Built

### Risk Domain Models (src/trading/risk/models.py)
- **ViolatedRule** enum with 16 values covering all rejection reasons (position size, Greeks exposure, loss limits, strategy restrictions, margin, circuit breaker, emergency)
- **TradeLeg**: Single leg of a multi-leg trade with symbol, action, quantity, optional options fields (right/strike/expiry), and ib_async contract/order references
- **GreeksImpact**: Net delta/gamma/theta/vega change from a trade
- **TradeProposal**: Complete trade request with legs, estimated Greeks, max loss, strategy type, account value, and auto-generated UUID proposal_id
- **MarginResult**: IB whatIfOrder response with margin values, commission, warning text, timeout flag
- **RiskDecision**: Approve/reject result with violated rule, details, evaluated_at timestamp, optional margin result, dry_run flag

### Risk Configuration (src/trading/risk/config.py)
- **PositionLimits**: max_position_pct (0-1), max_contracts (>0), max_dollars (>0) with Field(gt=0) constraints
- **GreeksLimits**: max_delta, max_gamma, max_vega (all >0), max_theta (negative = decay limit)
- **LossLimits**: daily_max_loss, weekly_max_loss (both >0)
- **StrategyRestrictions**: allowed_strategies list, allow_naked_options bool
- **RiskLimitsProfile**: Aggregates all limit categories plus margin_check_timeout and emergency_halt; field_validator rejects None subsections
- **RiskLimitsConfig**: Paper and live profiles with defaults

### Settings Integration
- Added `risk_limits: RiskLimitsConfig` field to Settings class
- Added risk_limits YAML section to default.yml with paper (relaxed) and live (strict) profiles
- Paper: max_dollars=10000, max_contracts=20, daily_max_loss=2000
- Live: max_dollars=5000, max_contracts=10, daily_max_loss=1000

### ORM Models (src/trading/db/models.py)
- **RiskDecisionRecord**: Full audit log with all margin fields, indexes on timestamp and proposal_id
- **CircuitBreakerState**: Per-mode/halt-type tracking with unique constraint, loss accumulators, updated_at with onupdate

### Alembic Migration 003
- Creates risk_decisions table with 16 columns, 2 indexes
- Creates circuit_breaker_state table with unique constraint on (mode, halt_type)
- Follows existing migration patterns (001, 002) exactly

## Verification Results

- All risk models importable from `trading.risk`
- Settings loads risk_limits from YAML with correct paper/live separation
- Field validators reject invalid values (negative limits, zero contracts, None subsections)
- ViolatedRule enum has all 16 values
- ORM models importable from `trading.db.models`
- Migration 003 is syntactically valid with correct revision chain
- All 126 existing tests pass

## Deviations from Plan

None -- plan executed exactly as written.

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Risk domain models and config | 9bb793c | risk/__init__.py, risk/models.py, risk/config.py, config.py, default.yml |
| 2 | ORM models and Alembic migration | 46856fc | db/models.py, 003_risk_engine_schema.py |

## Next Phase Readiness

All subsequent risk engine plans (03-02 through 03-06) can now import the domain models, config, and ORM models created here. No blockers identified.
