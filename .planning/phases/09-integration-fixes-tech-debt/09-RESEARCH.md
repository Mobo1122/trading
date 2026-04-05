# Phase 9: Integration Fixes & Tech Debt - Research

**Researched:** 2026-04-05
**Domain:** Cross-phase wiring fixes, dead code activation, tech debt closure
**Confidence:** HIGH

## Summary

Phase 9 resolves 3 critical cross-phase integration gaps and 5 tech debt items discovered by the v1 milestone audit. All issues are fully characterized with exact file locations and line numbers -- no ambiguity about what needs to change. The fixes are surgical: namespace string changes, new wiring calls, a property addition, and targeted test/doc corrections.

The 3 critical gaps (Redis namespace mismatch, circuit breaker dead code, health monitor property) are independent of each other and can be fixed in any order. Each has a well-defined root cause, a clear fix, and a straightforward verification. The tech debt items are similarly isolated and low-risk.

**Primary recommendation:** Split into two plans: Plan 01 covers the 3 critical gap fixes (namespace, circuit breaker wiring, health property) with their tests, and Plan 02 covers the 5 tech debt items (realized P&L writer, timing fix, commission test, doc fixes). Both plans are safe to execute in either order since they touch non-overlapping code.

## Standard Stack

This phase does not introduce new libraries. All fixes use the existing project stack.

### Core (already in project)
| Library | Purpose | Relevance to Phase 9 |
|---------|---------|----------------------|
| redis.asyncio | Async Redis client | Namespace key changes, HINCRBYFLOAT for loss accumulation, SET for realized P&L |
| SQLAlchemy 2.x | Async ORM with session factory | FillTracker DB queries for realized P&L aggregation |
| pytest / pytest-asyncio | Testing | New commission test, integration tests for wiring |
| structlog | Structured logging | Logging added to new wiring code |
| pydantic | Data models | QuoteSnapshot, HealthStatus already defined |
| FastAPI | Dashboard API | No route changes needed (route is correct, doc is wrong) |

### No New Dependencies
Phase 9 introduces zero new packages. Every fix uses APIs already imported and tested in the codebase.

## Architecture Patterns

### Pattern 1: Redis Namespace Convention
**What:** All market data in Redis follows the `mktdata:latest:{type}:{identifier}` pattern established by Phase 2's RedisDistributor.
**Current state (verified):**
```python
# src/trading/market_data/distributor.py line 44
QUOTE_HASH = "mktdata:latest:quote:{symbol}"
```
**Bug:** Three files use the old `market_data:{symbol}` pattern that was never written to:
- `src/trading/agents/scanner.py:139` -- `f"market_data:{symbol}"`
- `src/trading/agents/strategist.py:146` -- `f"market_data:{symbol}"`
- `src/trading/agents/pipeline.py:181` -- `f"market_data:{symbol}"`

**Fix pattern:** Replace the string literal in each f-string. The hash fields returned by HGETALL will be identical (same QuoteSnapshot fields). No downstream parsing changes needed.

**Docstring updates:** Scanner and strategist deps docstrings also reference `market_data:{symbol}` (scanner.py:48, strategist.py:49) and the regime detector docstring references it (regime.py:166). These should be updated for consistency.

### Pattern 2: Property Setter Wiring (Break Circular Dependencies)
**What:** Phase 4 established a pattern where `FillTracker` is injected into `OrderExecutionService` via a property setter after both objects are constructed, breaking the circular dependency.
**Current state (verified):**
```python
# src/trading/app.py:281-288
self.fill_tracker = FillTracker(session_factory=self.session_factory)
self.execution_service = OrderExecutionService(...)
self.execution_service.fill_tracker = self.fill_tracker
```
**Relevance:** The circuit breaker wiring should follow this same pattern. Add a `circuit_breaker` property to `FillTracker`, set it in app.py after construction.

### Pattern 3: Cached Property for Expensive Async Results
**What:** HealthMonitor.check_health() is async and makes 3 network calls (IB, DB, Redis). The DashboardPublisher needs a synchronous-looking accessor.
**Options:**
1. Add a `current_health` cached property that returns the last result from `check_health()` (requires calling check_health() periodically to refresh the cache)
2. Change `_publish_pipeline_status` to `await self._health_monitor.check_health()`

**Recommendation:** Option 2 (await check_health) is simpler and more correct. The publish loop is already async. Adding a cached property creates a staleness concern and requires a separate refresh mechanism. The DashboardPublisher already runs every N seconds, so calling check_health() each cycle adds minimal overhead (it already checks IB, DB, Redis -- those are fast).

### Pattern 4: Non-Fatal Integration (Project Convention)
**What:** Every cross-component call in this codebase is wrapped in try/except with logging, never crashing the caller. The circuit breaker call from FillTracker must follow this convention.
**Example from existing code:**
```python
# All alert publishing in pipeline.py follows this pattern:
try:
    await deps.redis_client.publish("alerts:trade_executed", ...)
except Exception:
    log.warning("pipeline.executor_node.alert_publish_failed", exc_info=True)
```

### Anti-Patterns to Avoid
- **Tight coupling:** Don't make FillTracker import CircuitBreaker directly. Use the property-setter pattern from Phase 4 to inject it.
- **Sync property wrapping async:** Don't create a sync property on HealthMonitor that calls async check_health() -- just make the publisher await it.
- **Ignoring race conditions:** The commission-before-fill race in FillTracker is already handled. The circuit breaker call must be placed where realized_pnl is available -- that's in `record_commission()` (and `_apply_commission()` for buffered commissions), not `record_fill()`, because IB's realized P&L comes on the CommissionReport, not the Fill.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Realized P&L aggregation | Custom Redis incrementor | SQL SUM query on ExecutionRecord.realized_pnl | DB is source of truth; Redis is cache |
| Redis key constants | Duplicated strings | Import from RedisDistributor.QUOTE_HASH or define a shared constant | Prevents future namespace drift |
| Async property caching | Custom cache mechanism | Just await check_health() in the async publisher | Publisher is already async; no need for complexity |

**Key insight:** The root cause of Gap 1 was duplicated Redis key strings. The fix should include establishing a shared constant so this class of bug cannot recur.

## Common Pitfalls

### Pitfall 1: Realized P&L Location in IB Event Flow
**What goes wrong:** Putting the circuit breaker call in `record_fill()` instead of `record_commission()`.
**Why it happens:** Intuition says "fill = trade = P&L", but IB separates fill events (price/quantity) from commission reports (commission + realizedPNL). The `realizedPNL` field only exists on `CommissionReport`, not `Fill.execution`.
**How to avoid:** Wire circuit_breaker.record_realized_loss() in `record_commission()` and `_apply_commission()` (the buffered-commission path), reading from `report.realizedPNL`. Check for `float("inf")` (IB sentinel for "not applicable").
**Warning signs:** If record_realized_loss is called from record_fill, the loss_amount will always be 0 or None.

### Pitfall 2: IB's realizedPNL Sentinel Value
**What goes wrong:** Treating `float("inf")` as a real P&L value.
**Why it happens:** IB returns `realizedPNL = float("inf")` when the report has no P&L to report (e.g., opening a new position). The existing code already guards against this (fill_tracker.py:247: `if report.realizedPNL != float("inf")`).
**How to avoid:** The circuit breaker call must include the same guard. Only call `record_realized_loss()` when realizedPNL is not `float("inf")` AND the value is negative (a loss).
**Warning signs:** Circuit breaker triggering on position opens (realizedPNL = inf).

### Pitfall 3: Loss vs. Profit Semantics
**What goes wrong:** Passing IB's realized P&L directly to `record_realized_loss()`.
**Why it happens:** IB reports realized P&L as a signed number (negative = loss, positive = profit). `CircuitBreaker.record_realized_loss(loss_amount)` expects a positive number representing a loss (line 121: `if loss_amount <= 0: return`).
**How to avoid:** Negate the IB value when it's negative: `if realized_pnl < 0: circuit_breaker.record_realized_loss(abs(realized_pnl))`.
**Warning signs:** Profitable trades being accumulated as losses.

### Pitfall 4: QuoteSnapshot Has No prev_close Field
**What goes wrong:** Assuming the namespace fix will give the regime detector full momentum data.
**Why it happens:** The regime detector reads `pdata.get("prev_close")` (regime.py:191), but `QuoteSnapshot` does not have a `prev_close` field. Even after fixing the namespace, the HGETALL result will not contain `prev_close`.
**How to avoid:** Acknowledge this as a known limitation. The namespace fix still improves agent behavior because scanner and strategist will get bid/ask/last/volume/IV. The regime detector will get `last` but not `prev_close`, so momentum will remain unavailable. IV-based volatility classification will work correctly (that comes from `iv_engine.compute_batch()`, not Redis).
**Impact:** MEDIUM. The regime detector's trend signal will default to "neutral" (no momentum data), but volatility signal from IV will work. Regime detection will be partial but functional. Full momentum support would require either: (a) adding prev_close to QuoteSnapshot (upstream IB data change), or (b) computing prev_close from TimescaleDB historical data. Both are out of scope for Phase 9.

### Pitfall 5: Dashboard Realized P&L Writer Placement
**What goes wrong:** Writing to `dashboard:realized_pnl` from FillTracker (tightly couples execution and dashboard).
**Why it happens:** FillTracker has access to realized P&L data.
**How to avoid:** Write it from `DashboardPublisher._publish_loop()` using a SQL query. The publisher already runs every N seconds and has access to the session factory (or it can be added). Alternatively, write it from the FillTracker's `record_commission()` using Redis INCRBYFLOAT for atomic accumulation. Both approaches work; the publisher approach keeps separation of concerns cleaner.
**Recommendation:** Use DashboardPublisher since it already owns the `dashboard:*` namespace. Add a `_publish_realized_pnl()` method that queries the DB (SUM of ExecutionRecord.realized_pnl WHERE realized_pnl IS NOT NULL AND realized_pnl != 0) and writes to `dashboard:realized_pnl`.

## Code Examples

### Fix 1: Redis Namespace (scanner.py, strategist.py, pipeline.py)

```python
# BEFORE (scanner.py:139):
data = await ctx.deps.redis_client.hgetall(f"market_data:{symbol}")

# AFTER:
data = await ctx.deps.redis_client.hgetall(f"mktdata:latest:quote:{symbol}")
```

Same pattern in all three files. Also update docstrings:
```python
# scanner.py:48 and strategist.py:49 docstring
# BEFORE: via ``HGET market_data:{symbol}``
# AFTER:  via ``HGETALL mktdata:latest:quote:{symbol}``
```

### Fix 2: Circuit Breaker Wiring (fill_tracker.py)

```python
# Add property to FillTracker (same pattern as execution_service.py:63-74):
class FillTracker:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._pending_commissions = {}
        self._circuit_breaker = None  # NEW

    @property
    def circuit_breaker(self):
        return self._circuit_breaker

    @circuit_breaker.setter
    def circuit_breaker(self, value):
        self._circuit_breaker = value
```

```python
# In record_commission(), after updating exec_record.realized_pnl:
if report.realizedPNL != float("inf") and report.realizedPNL < 0:
    if self._circuit_breaker is not None:
        try:
            await self._circuit_breaker.record_realized_loss(
                abs(report.realizedPNL)
            )
        except Exception:
            logger.warning(
                "circuit_breaker_record_failed",
                order_id=order_id,
                exec_id=exec_id,
                exc_info=True,
            )
```

```python
# In app.py, after line 288:
self.fill_tracker.circuit_breaker = self.circuit_breaker
```

### Fix 3: HealthMonitor in DashboardPublisher

```python
# BEFORE (publisher.py:117-129):
async def _publish_pipeline_status(self) -> None:
    try:
        status = "idle"
        if self._health_monitor is not None:
            try:
                health = self._health_monitor.current_health  # AttributeError!
                if hasattr(health, "value"):
                    status = health.value
                elif isinstance(health, str):
                    status = health
            except Exception:
                pass
        await self._redis.set("dashboard:pipeline_status", status)
    except Exception:
        ...

# AFTER:
async def _publish_pipeline_status(self) -> None:
    try:
        status = "idle"
        if self._health_monitor is not None:
            try:
                health_status = await self._health_monitor.check_health()
                status = health_status.overall.value
            except Exception:
                pass
        await self._redis.set("dashboard:pipeline_status", status)
    except Exception:
        ...
```

### Fix 4: Regime Detector Timing Bug (pipeline.py)

```python
# BEFORE (pipeline.py:163-196):
classification = await deps.regime_detector.detect(iv_batch, price_data)
t0 = time.monotonic()  # BUG: t0 set AFTER detect, never used for duration

await log_agent_decision(
    ...
    duration_ms=0,  # hardcoded to 0
    ...
)

# AFTER:
t0 = time.monotonic()  # MOVED: before detect()
classification = await deps.regime_detector.detect(iv_batch, price_data)
duration_ms = int((time.monotonic() - t0) * 1000)

await log_agent_decision(
    ...
    duration_ms=duration_ms,  # actual duration
    ...
)
```

### Fix 5: Realized P&L Publisher

```python
# New method in DashboardPublisher:
async def _publish_realized_pnl(self) -> None:
    """Publish cumulative realized P&L from execution records to Redis."""
    try:
        if self._session_factory is None:
            return
        async with get_session(self._session_factory) as session:
            from sqlalchemy import func, select
            from trading.db.models import ExecutionRecord
            result = await session.execute(
                select(func.coalesce(func.sum(ExecutionRecord.realized_pnl), 0.0))
                .where(ExecutionRecord.realized_pnl.isnot(None))
            )
            total = float(result.scalar_one())
        await self._redis.set("dashboard:realized_pnl", str(round(total, 2)))
    except Exception:
        self._log.warning("dashboard_publisher.realized_pnl_failed", exc_info=True)
```

Note: DashboardPublisher currently receives `redis_client` and `ib` but not `session_factory`. The constructor will need to accept an optional `session_factory` parameter.

## Exact Files Changed

### Gap 1: Redis Namespace Mismatch (3 files, ~6 lines each)
| File | Line | Change |
|------|------|--------|
| `src/trading/agents/scanner.py` | 48 | Docstring: `market_data:{symbol}` -> `mktdata:latest:quote:{symbol}` |
| `src/trading/agents/scanner.py` | 139 | Key: `f"market_data:{symbol}"` -> `f"mktdata:latest:quote:{symbol}"` |
| `src/trading/agents/strategist.py` | 49 | Docstring: `market_data:{symbol}` -> `mktdata:latest:quote:{symbol}` |
| `src/trading/agents/strategist.py` | 146 | Key: `f"market_data:{symbol}"` -> `f"mktdata:latest:quote:{symbol}"` |
| `src/trading/agents/pipeline.py` | 181 | Key: `f"market_data:{symbol}"` -> `f"mktdata:latest:quote:{symbol}"` |
| `src/trading/agents/regime.py` | 166 | Docstring: `market_data:{symbol}` -> `mktdata:latest:quote:{symbol}` |

### Gap 2: Circuit Breaker Wiring (2 files)
| File | Lines | Change |
|------|-------|--------|
| `src/trading/orders/fill_tracker.py` | 44-46, 247-248, 377-378 | Add `_circuit_breaker` property; call `record_realized_loss()` in `record_commission()` and `_apply_commission()` when realizedPNL < 0 |
| `src/trading/app.py` | After 288 | Wire: `self.fill_tracker.circuit_breaker = self.circuit_breaker` |

### Gap 3: Health Monitor Property (1 file)
| File | Lines | Change |
|------|-------|--------|
| `src/trading/dashboard/publisher.py` | 117-129 | Change `self._health_monitor.current_health` to `await self._health_monitor.check_health()`, use `.overall.value` |

### Tech Debt Items (5 files)
| Item | File | Change |
|------|------|--------|
| Timing bug | `src/trading/agents/pipeline.py` | Move `t0 = time.monotonic()` before `detect()`, use computed `duration_ms` |
| Missing test | `tests/test_order_execution.py` | Add `test_record_commission_updates_record` in TestFillTracker class |
| Realized P&L | `src/trading/dashboard/publisher.py` | Add `_publish_realized_pnl()` method, add `session_factory` constructor param, call from `_publish_loop()` |
| Realized P&L | `src/trading/app.py` | Pass `session_factory=self.session_factory` to DashboardPublisher constructor |
| Doc route | `.planning/phases/07-dashboard-monitoring/*.md` | Where applicable, correct `GET /api/trades` to `GET /api/trades/history` |
| Verification discrepancy | `.planning/phases/08-alerts-autonomy/08-VERIFICATION.md` | Change body text `Status: gaps_found` to `Status: passed` (frontmatter is correct; gap was fixed in commit 853b6f6) |

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Duplicated Redis key strings | Should use shared constants from RedisDistributor | Prevents namespace drift; this phase should optionally introduce a helper or import |
| `HealthMonitor.current_health` (sync property) | `await check_health()` (async method) | check_health() is the only API; the property was never implemented |
| FillTracker operates in isolation | FillTracker reports losses to CircuitBreaker | Completes the loss-limit feedback loop |

## Open Questions

1. **Should Redis namespace constants be centralized?**
   - What we know: RedisDistributor defines `QUOTE_HASH = "mktdata:latest:quote:{symbol}"` as a class constant. The agent files hardcode their own strings.
   - What's unclear: Whether to import from RedisDistributor (creates a dependency from agents -> market_data) or to define a shared `redis_keys.py` module.
   - Recommendation: For Phase 9, just fix the strings. A shared constants module is a good future improvement but not required for correctness.

2. **Should the regime detector's momentum calculation be fixed?**
   - What we know: `QuoteSnapshot` has no `prev_close` field. Even after the namespace fix, `price_data[symbol].get("prev_close")` will return None. The regime detector will classify volatility correctly (from IV data) but trend will default to "neutral".
   - What's unclear: Whether this is a P9 concern or a future enhancement.
   - Recommendation: Out of scope for Phase 9. The audit identified the namespace mismatch, not the missing field. Document this as a known limitation. IV-based regime detection will work; momentum-based detection requires upstream data model changes.

3. **DashboardPublisher session_factory access**
   - What we know: The publisher currently takes `redis_client`, `ib`, `health_monitor`, and `interval`. It does not have `session_factory`. Writing realized P&L from the publisher requires DB access.
   - What's unclear: Whether to add session_factory to publisher or use an alternative approach (e.g., Redis INCRBYFLOAT in FillTracker).
   - Recommendation: Add optional `session_factory` parameter to DashboardPublisher constructor. The publisher already runs periodic DB-adjacent work (positions via IB). A single SUM query every 5 seconds is negligible overhead.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection of all files listed in the milestone audit
- `src/trading/market_data/distributor.py:44` -- confirms `mktdata:latest:quote:{symbol}` pattern
- `src/trading/risk/circuit_breaker.py:111-149` -- confirms `record_realized_loss()` API
- `src/trading/core/health.py:85-121` -- confirms only `check_health()` async method exists
- `src/trading/orders/fill_tracker.py:247-248` -- confirms realizedPNL guard pattern
- `src/trading/app.py:281-288` -- confirms property-setter wiring pattern
- `.planning/v1-MILESTONE-AUDIT.md` -- authoritative gap descriptions

### Secondary (MEDIUM confidence)
- IB API behavior (realizedPNL = float("inf") for non-applicable) -- verified from existing guard code in fill_tracker.py

## Metadata

**Confidence breakdown:**
- Gap analysis: HIGH -- all gaps verified by direct code inspection with exact line numbers
- Fix patterns: HIGH -- all fixes use patterns already established in the codebase
- Tech debt items: HIGH -- each item has a clear root cause and a straightforward fix
- Pitfalls: HIGH -- documented from actual code behavior, not speculation
- Open questions: MEDIUM -- momentum gap is a real finding but scope decision is subjective

**Research date:** 2026-04-05
**Valid until:** Indefinite (all findings are based on current codebase state, not external libraries)
