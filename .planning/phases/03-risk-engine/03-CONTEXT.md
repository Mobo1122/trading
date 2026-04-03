# Phase 3: Risk Engine - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

A deterministic risk gate that every trade proposal must pass through before any execution can proceed. The engine enforces position sizing, Greeks exposure, loss limits, and strategy restrictions — all based on configurable rules, with no AI involvement. Phase 3 does not place orders; it approves or rejects proposals. Order placement is Phase 4.

</domain>

<decisions>
## Implementation Decisions

### Evaluation Interface
- Returns a structured `RiskDecision` object: `approved` (bool) + `violated_rule` (enum) + `details` (human-readable string, e.g., "POSITION_SIZE_EXCEEDED: $8,500 > $5,000 limit")
- Trade proposals must include all legs, estimated Greeks impact (delta, gamma, theta, vega), and max loss scenario — caller pre-computes this, risk engine validates against limits
- Supports a **dry-run mode**: `check_trade()` evaluates a proposal without side effects (does not count toward limit accumulation) — enables agents to pre-screen proposals
- Invocation pattern: **Claude's Discretion** — must satisfy the fail-safe requirement (unreachable = block all trades from Phase 3 success criterion #5)

### Circuit Breaker Behavior
- Loss limit basis: **Claude's Discretion** — default to realized losses only (closed trades), as mark-to-market would create false positives on short options that are temporarily OTM
- On breach: **block new trades only** — existing open positions are not force-closed; they can expire or be manually managed
- State persistence: **Redis (hot path) + Postgres (source of truth)** — Redis checked on every evaluation; on startup, risk engine loads halt state from Postgres to recover after restarts
- Reset schedule: **auto-reset at market open** — daily limits reset at 9:30am ET; weekly limits reset Monday at 9:30am ET (no manual intervention required for normal operation)

### Configuration Management
- Limits stored in **YAML as defaults, Postgres DB as runtime overrides** — YAML provides baseline; any DB-persisted override takes precedence; consistent with Phase 1 config pattern
- Invalid config values (negative limits, zero max_contracts): **Claude's Discretion** — recommend hard fail on startup (refuse to start) for safety; risk limits with bad values are more dangerous than a refused boot
- Paper/live separation: **Claude's Discretion** — recommend separate limit profiles (paper: / live: sections) so paper trading reflects realistic constraints without risking overfitting to live limits
- **Emergency tighten mode**: admin command (CLI or config flag) can cut position size limits and halt new trades at runtime without a config file change — implemented as a runtime DB override, cleared explicitly or on restart

### Pre-Trade Margin Check (IB whatIfOrder)
- **Mandatory check, timeout falls through**: run `whatIfOrder` for every trade; if IB Gateway doesn't respond within timeout, proceed to other rules (not a hard block)
- Rejection threshold: **Claude's Discretion** — recommend reject if IB projects insufficient excess liquidity (i.e., trade would exceed available margin), not a percentage cap
- Timeout: **Claude's Discretion** — recommend 5 seconds (gives IB Gateway time under normal load without blocking the pipeline excessively)
- **Audit logging**: `whatIfOrder` result (projected margin, estimated commission, IB's margin classification) stored alongside the `RiskDecision` record — required for post-trade audit

### Claude's Discretion
- Loss limit basis (realized vs. mark-to-market) — recommend realized only
- Invocation pattern for fail-safe (in-process with timeout wrapper vs. Redis request/response)
- Invalid config handling — recommend hard fail on startup
- Paper/live limit profiles — recommend separate per-mode profiles
- `whatIfOrder` rejection threshold — recommend IB-projected insufficient margin
- `whatIfOrder` timeout duration — recommend 5 seconds

</decisions>

<specifics>
## Specific Ideas

- The fail-safe requirement is strict: "when the risk manager process is unreachable or unresponsive, zero trades execute" — invocation design must account for this explicitly
- Circuit breaker state must survive crashes and restarts — Postgres is the authoritative store, Redis is the hot-path cache
- Dry-run mode is a first-class feature, not an afterthought — agents will use it to screen proposals before committing

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-risk-engine*
*Context gathered: 2026-04-03*
