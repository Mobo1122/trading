---
phase: "06-advanced-agent-intelligence"
plan: "01"
subsystem: "agent-intelligence"
tags: ["regime-detection", "market-classification", "hysteresis", "strategy-weights"]
dependency_graph:
  requires:
    - "02-market-data-analytics"  # IVData model, Redis market_data keys
    - "05-core-agent-pipeline"     # AgentConfig, PipelineState
  provides:
    - "MarketRegime enum (6 regimes)"
    - "RegimeDetector with hysteresis"
    - "REGIME_STRATEGY_WEIGHTS mapping"
    - "RegimeConfig in AgentConfig"
    - "regime_classification field in PipelineState"
  affects:
    - "06-02"  # Scanner enhancement will consume regime classification
    - "06-03"  # Expiration monitor will use regime context
tech_stack:
  added: []
  patterns:
    - "Deterministic classification (not ML) for auditability"
    - "Hysteresis state machine for regime stability"
    - "VIX as supplementary volatility signal"
key_files:
  created:
    - "src/trading/agents/regime.py"
  modified:
    - "src/trading/agents/config.py"
    - "src/trading/agents/state.py"
decisions:
  - id: "06-01-01"
    description: "Deterministic regime detection (not ML) for testability, explainability, auditability in real-money system"
  - id: "06-01-02"
    description: "Hysteresis prevents whiplash: regime must persist N consecutive checks before switching"
  - id: "06-01-03"
    description: "VIX as supplementary signal -- upgrades volatility to high but only downgrades from normal (not from high)"
  - id: "06-01-04"
    description: "RegimeClassification lives in regime.py as domain model, not in models.py (co-located with detector)"
  - id: "06-01-05"
    description: "PipelineState extended with rolling_candidates and rolling_decisions now to avoid future edit"
metrics:
  duration: "3min"
  completed: "2026-04-04"
---

# Phase 06 Plan 01: Market Regime Detection Summary

Deterministic regime detector classifying market as one of 6 regimes from IV rank averages and price momentum, with hysteresis to prevent whiplash and strategy weight mapping per regime.

## Tasks Completed

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | RegimeConfig and PipelineState extension | 8f91c2b | RegimeConfig model, AgentConfig.regime field, PipelineState new fields |
| 2 | Deterministic regime detection module | 29c409b | MarketRegime enum, RegimeClassification, RegimeDetector, REGIME_STRATEGY_WEIGHTS |

## Implementation Details

### RegimeConfig (config.py)
Pydantic BaseModel with 9 fields controlling regime detection behavior: `enabled`, `hysteresis_count` (default 3), IV rank thresholds (30/60), momentum thresholds (+/-0.02), VIX thresholds (15/25), and `momentum_lookback_days`. Added as `regime` field to `AgentConfig`.

### PipelineState (state.py)
Extended with three new fields: `regime_classification: dict` (serialized RegimeClassification), `rolling_candidates: list[dict]`, and `rolling_decisions: list[dict]`. The rolling fields are pre-added for Plan 02 to avoid a redundant edit.

### RegimeDetector (regime.py, 504 lines)
- **MarketRegime enum**: 6 string-valued members (BULL_QUIET, BULL_VOLATILE, BEAR_QUIET, BEAR_VOLATILE, SIDEWAYS, UNKNOWN) for JSON serialization
- **RegimeClassification**: Pydantic model with regime, confidence (0-1), trend/volatility signals, raw indicators dict, reasoning string, and previous_regime for audit trail
- **REGIME_STRATEGY_WEIGHTS**: Maps each regime to strategy distributions (covered_call, cash_secured_put, vertical_spread, iron_condor, calendar_spread)
- **RegimeDetector.detect()**: Async method computing IV rank average, price momentum average, classifying volatility/trend signals, mapping to regime, applying hysteresis, computing confidence
- **Hysteresis**: Consecutive counter tracks pending regime; only switches after N consecutive detections agree; resets on regime match or new pending
- **Confidence scoring**: Base 0.5 + 0.2 (IV coverage >50%) + 0.2 (momentum available) + 0.1 (regime consistency)
- **VIX supplementary**: Upgrades volatility to "high" if VIX > threshold; only downgrades from "normal" (never overrides IV-confirmed "high")
- **Graceful degradation**: Empty/insufficient data returns UNKNOWN with confidence 0.0 and descriptive reasoning

## Decisions Made

1. **Deterministic not ML**: Regime detection uses threshold-based classification for testability, explainability, and auditability in a real-money system.
2. **Hysteresis state machine**: Prevents regime whiplash where rapid oscillation would cause scanner to flip strategies every pipeline run. Default 3 consecutive checks.
3. **VIX asymmetric influence**: VIX can upgrade volatility to "high" (conservative) but only downgrades from "normal" -- respects IV rank when it says "high" even if VIX is low.
4. **Domain model co-location**: RegimeClassification lives in `regime.py` alongside RegimeDetector rather than in `models.py`, keeping the domain model with its producer.
5. **Pre-added rolling state fields**: Added `rolling_candidates` and `rolling_decisions` to PipelineState now to avoid a second edit when Plan 02 needs them.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

All verification criteria passed:
- `from trading.agents.regime import RegimeDetector, MarketRegime, REGIME_STRATEGY_WEIGHTS` -- imports work
- `AgentConfig().regime` returns RegimeConfig with correct defaults
- `PipelineState.__annotations__` includes `regime_classification`, `rolling_candidates`, `rolling_decisions`
- Empty input returns UNKNOWN with confidence 0.0 (no crash)
- Hysteresis blocks premature regime switch, allows after threshold
- VIX supplementary signal correctly upgrades volatility
- All 6 regimes have strategy weight mappings

## Next Phase Readiness

Plan 06-02 (scanner enhancement) can proceed. It will:
- Import `RegimeDetector` and `REGIME_STRATEGY_WEIGHTS` from `regime.py`
- Call `detector.detect()` at scanner node start
- Serialize `RegimeClassification` into `PipelineState.regime_classification`
- Use `rolling_candidates` and `rolling_decisions` state fields
