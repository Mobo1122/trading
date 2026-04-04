---
phase: "06-advanced-agent-intelligence"
plan: "03"
subsystem: "agent-intelligence"
tags: ["pipeline-wiring", "regime-context", "rolling-integration", "scanner-prompt", "app-lifecycle"]
dependency_graph:
  requires:
    - "06-01"  # RegimeDetector, RegimeClassification, REGIME_STRATEGY_WEIGHTS, MarketRegime
    - "06-02"  # ExpirationMonitor, RollingCandidate, RollingDecision, RollingConfig
    - "05-core-agent-pipeline"  # PipelineDeps, create_pipeline, run_pipeline, PipelineState
  provides:
    - "regime_detector node in pipeline topology (START -> regime_detector -> scanner)"
    - "regime context injection into scanner prompt"
    - "rolling pre-check in run_agent_pipeline()"
    - "app lifecycle wiring for RegimeDetector and ExpirationMonitor"
    - "26 comprehensive Phase 6 tests"
  affects:
    - "07-monitoring-observability"  # regime/rolling decisions logged for monitoring
    - "08-deployment-live-trading"   # all Phase 6 components wired into production app
tech_stack:
  added: []
  patterns:
    - "regime context prepended to LLM prompt via prompt_prefix parameter"
    - "rolling pre-check in app convenience method (not in pipeline internals)"
    - "non-fatal regime detection (empty dict on error/disabled)"
key_files:
  created:
    - "tests/test_agents.py (Phase 6 test additions: 26 new tests)"
  modified:
    - "src/trading/agents/pipeline.py"
    - "src/trading/agents/scanner.py"
    - "src/trading/agents/logging.py"
    - "src/trading/agents/__init__.py"
    - "src/trading/app.py"
decisions:
  - key: "regime-context-via-prompt-prefix"
    decision: "Inject regime context into scanner prompt via prompt_prefix parameter rather than modifying agent instructions"
    rationale: "Keeps agent instructions static and testable; runtime context adapts dynamically without changing agent definition"
  - key: "rolling-precheck-in-app-not-pipeline"
    decision: "scan_expiring_positions called in app.run_agent_pipeline(), not inside pipeline node"
    rationale: "Cleaner separation -- app handles IB query orchestration, pipeline receives serialized data"
  - key: "regime-node-non-fatal"
    decision: "Regime detection errors return empty dict, scanner runs without regime context"
    rationale: "Regime is advisory, not required for correct pipeline operation"
metrics:
  duration: "8min"
  completed: "2026-04-04"
---

# Phase 6 Plan 03: Pipeline Wiring, Scanner Injection, App Lifecycle & Tests Summary

Regime detection node wired as first pipeline node (START -> regime_detector -> scanner), scanner prompt dynamically prepends regime context (name, confidence, strategy weights), rolling candidates pre-scanned in app layer and injected into pipeline state, 26 comprehensive tests validate all Phase 6 integration without LLM API key.

## What Was Done

### Task 1: Pipeline Regime Node, Scanner Prompt Injection, and Logging Updates

**Pipeline topology update (`pipeline.py`):**
- Added `_regime_node()` that calls `RegimeDetector.detect()` with IV batch and Redis price data
- Updated `create_pipeline()` graph: START -> regime_detector -> scanner -> [conditional] -> strategist -> risk_manager -> [conditional] -> executor -> END
- Extended `PipelineDeps` with `regime_detector` and `expiration_monitor` fields (typed `Any`, optional)
- Extended `run_pipeline()` with `regime_classification` and `rolling_candidates` parameters
- Initial state now includes `regime_classification`, `rolling_candidates`, `rolling_decisions`

**Scanner regime context injection (`pipeline.py` + `scanner.py`):**
- `_scan_node()` builds regime context string from `state["regime_classification"]`
- Context includes: regime name, confidence percentage, trend/volatility signals, strategy weight mix
- Passed to `run_scanner()` as `prompt_prefix` parameter, prepended to existing prompt
- When regime is UNKNOWN or empty, no prefix is added (scanner runs normally)

**Logging updates (`logging.py`):**
- `STAGE_ORDER` extended with `regime_detector: 0` and `rolling_monitor: 5`
- `_get_output_summary()` handles RegimeClassification-like outputs (checks for `regime` attribute)

**Package docstring (`__init__.py`):**
- Updated to mention Phase 6 regime detection and rolling modules

### Task 2: App Wiring and Comprehensive Phase 6 Tests

**App lifecycle wiring (`app.py`):**
- `RegimeDetector` created in `startup()` when `settings.agents.regime.enabled` is True
- Wired into `pipeline_deps.regime_detector` immediately after creation
- `ExpirationMonitor` created in `connect_ib()` (needs IB connection) when `settings.agents.rolling.enabled` is True
- Wired into `pipeline_deps.expiration_monitor`
- `run_agent_pipeline()` convenience method: scans rolling candidates via `scan_expiring_positions()`, serializes to dicts, passes to `run_pipeline()` as `rolling_candidates`
- All creation steps are non-critical (try/except with warning log)

**Comprehensive Phase 6 tests (26 new tests in `test_agents.py`):**
- Regime detection: enum values, classification serialization, strategy weights completeness, detector with empty data, bull_quiet detection, hysteresis behavior, config defaults
- Rolling logic: candidate model, decision model, empty positions, options-only filter, DTE threshold filter, close-on-excessive-loss, roll recommendation, config defaults
- Pipeline integration: Phase 6 state fields, STAGE_ORDER entries, PipelineDeps fields, regime_detector in compiled graph, run_pipeline/run_scanner parameter signatures
- App wiring: regime detector creation, disabled config, Phase 6 init defaults, run_agent_pipeline without compilation, rolling scan -> pipeline flow

## Decisions Made

1. **Regime context via prompt_prefix**: Inject regime context into scanner prompt via a `prompt_prefix` parameter rather than modifying agent instructions. Keeps agent definition static/testable; runtime context adapts dynamically.

2. **Rolling pre-check in app, not pipeline**: `scan_expiring_positions()` called in `app.run_agent_pipeline()`, not inside a pipeline node. Cleaner separation -- app handles IB query orchestration, pipeline receives serialized data.

3. **Regime node non-fatal**: Regime detection errors return empty dict `{}`, scanner runs without regime context. Regime is advisory, not required for correct pipeline operation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale STAGE_ORDER test assertion**
- **Found during:** Task 1
- **Issue:** Existing `test_stage_order_mapping` asserted `len(STAGE_ORDER) == 4` which failed after adding regime_detector and rolling_monitor entries
- **Fix:** Updated assertion to check for all 6 entries including new Phase 6 agents
- **Files modified:** `tests/test_agents.py`
- **Commit:** f0f75fa

## Test Results

- **Total tests:** 84 (58 Phase 5 + 26 Phase 6)
- **All passing:** Yes
- **No regressions:** Confirmed
- **No LLM API key required:** All tests use mocks

## Next Phase Readiness

Phase 6 is now complete. All three plans executed:
- Plan 01: Regime detection module (RegimeDetector, MarketRegime, strategy weights)
- Plan 02: Rolling logic module (ExpirationMonitor, RollingCandidate, RollingDecision)
- Plan 03: Pipeline wiring, scanner injection, app lifecycle, comprehensive tests

Ready for Phase 7 (Monitoring & Observability) which will build on the decision logging infrastructure and regime/rolling audit trail established here.
