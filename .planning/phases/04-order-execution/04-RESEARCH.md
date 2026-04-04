# Phase 4: Order Execution - Research

**Researched:** 2026-04-03
**Domain:** IB order placement, multi-leg combo orders, fill tracking, reconnection recovery
**Confidence:** HIGH

## Summary

Phase 4 builds the order execution layer that bridges the risk engine (Phase 3) to IB Gateway via ib_async. The core work is: (1) an OrderExecutionService that takes a TradeProposal, runs it through evaluate_with_failsafe(), then calls ib.placeOrder() with the correct contract/order types, (2) a ComboOrderBuilder that constructs BAG contracts with ComboLegs for multi-leg spreads, (3) a FillTracker that listens to IB's Trade events (statusEvent, fillEvent, commissionReportEvent) and records execution details with slippage calculations, and (4) a reconnection recovery flow that calls reqOpenOrdersAsync() after reconnect and reconciles in-flight orders with database state.

The existing codebase provides strong foundations: OrderStateMachine and OrderTracker (Phase 1) handle state transitions and DB persistence, RiskManager.check_trade() and evaluate_with_failsafe() (Phase 3) provide the risk gate, IBConnectionManager (Phase 1) handles connection lifecycle with auto-reconnect, and ContractResolver (Phase 2) handles contract qualification. The primary new work is wiring these together into a coherent order submission pipeline and adding fill/execution tracking.

ib_async's placeOrder() returns a Trade object that is kept live-updated with status changes, fills, and commissions. The Trade object has per-trade events (statusEvent, fillEvent, commissionReportEvent) that should be subscribed to for each placed order. For combo orders, IB uses BAG contracts with ComboLeg objects specifying conId, ratio, action, and exchange. Non-guaranteed combos require a TagValue("NonGuaranteed", "1") in smartComboRoutingParams.

**Primary recommendation:** Build an OrderExecutionService as the single entry point for all order placement. It owns the flow: validate proposal via risk gate -> construct IB contract/order -> place via ib.placeOrder() -> subscribe to Trade events -> bridge events to OrderTracker. No order reaches IB without passing through this service.

## Standard Stack

### Core (already in project -- no new dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ib_async | >=2.1.0 | placeOrder, cancelOrder, Trade events, Bag/ComboLeg, reqOpenOrders | Already the IB connectivity layer; provides all order placement and tracking APIs |
| python-statemachine | >=3.0.0 | OrderStateMachine for lifecycle tracking | Already built in Phase 1; drives CREATED->FILLED state flow |
| sqlalchemy[asyncio] | >=2.0.48 | Order, OrderStateTransition, new ExecutionRecord persistence | Already used for all DB operations |
| pydantic | >=2.12.5 | TradeProposal, RiskDecision, new ExecutionRecord models | Already used for all domain models |
| structlog | >=25.5.0 | Structured logging for order lifecycle | Already used everywhere |

### Supporting (already in project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| redis[hiredis] | >=7.4.0 | Publish order status updates for dashboard (Phase 7) | Optional; prep for Phase 7 |
| alembic | >=1.18.4 | Migration for execution_records table | Schema changes for fill tracking |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Per-trade event subscriptions | Global ib.orderStatusEvent handler | Per-trade is cleaner: each Trade object has its own events; global handler requires routing logic |
| Custom combo builder | Manually constructing Contract() with comboLegs | Bag() constructor auto-sets secType="BAG"; use it |
| Polling trade.isDone() | Event-driven via statusEvent | Events are non-blocking and immediate; never poll |

**Installation:**
```bash
# No new dependencies required. All libraries already in pyproject.toml.
```

## Architecture Patterns

### Recommended Project Structure
```
src/trading/
  orders/
    __init__.py              # Public API exports
    state_machine.py         # OrderStateMachine (existing Phase 1)
    tracker.py               # OrderTracker (existing Phase 1)
    execution_service.py     # NEW: OrderExecutionService - single entry point
    combo_builder.py         # NEW: ComboOrderBuilder - BAG contract construction
    fill_tracker.py          # NEW: FillTracker - IB event -> DB persistence
    models.py                # NEW: ExecutionRecord, SlippageReport Pydantic models
    recovery.py              # NEW: OrderRecoveryManager - reconnect reconciliation
```

### Pattern 1: Risk-Gated Order Submission Pipeline
**What:** Every order flows through a single async method that enforces risk checks before IB submission.
**When to use:** Every order placement, no exceptions.
**Example:**
```python
# Source: Derived from existing RiskManager + ib_async placeOrder API
from ib_async import IB, MarketOrder, LimitOrder, StopOrder, Option, Trade
from trading.risk.manager import evaluate_with_failsafe, RiskManager
from trading.risk.models import TradeProposal, RiskDecision

class OrderExecutionService:
    def __init__(
        self,
        ib: IB,
        risk_manager: RiskManager,
        order_tracker: OrderTracker,
        fill_tracker: FillTracker,
        session_factory,
    ):
        self._ib = ib
        self._risk_manager = risk_manager
        self._order_tracker = order_tracker
        self._fill_tracker = fill_tracker
        self._session_factory = session_factory

    async def submit_order(
        self,
        proposal: TradeProposal,
        timeout: float = 10.0,
    ) -> tuple[RiskDecision, Trade | None]:
        """Risk-gated order submission. Returns (decision, trade).

        Trade is None if risk check rejected the proposal.
        """
        # 1. Risk gate -- ALWAYS first, no bypass
        decision = await evaluate_with_failsafe(
            self._risk_manager, proposal, timeout=timeout
        )
        if not decision.approved:
            return decision, None

        # 2. Construct IB contract and order from proposal
        # 3. Create DB Order record
        # 4. Create state machine via OrderTracker
        # 5. Place order via ib.placeOrder(contract, order)
        # 6. Subscribe to Trade events for fill tracking
        # 7. Return decision and Trade
        ...
```

### Pattern 2: Per-Trade Event Subscription
**What:** Subscribe to each Trade object's events individually rather than using global IB events.
**When to use:** After every placeOrder() call.
**Example:**
```python
# Source: ib_async API docs - Trade object events
trade = ib.placeOrder(contract, order)

# Subscribe to this specific trade's events
trade.statusEvent += lambda t: on_status_change(order_id, t)
trade.fillEvent += lambda t, f: on_fill(order_id, t, f)
trade.commissionReportEvent += lambda t, f, r: on_commission(order_id, t, f, r)
```

### Pattern 3: BAG Contract for Multi-Leg Combos
**What:** Use ib_async Bag contract with ComboLeg objects for spread orders.
**When to use:** Any multi-leg order (verticals, iron condors, butterflies, etc.).
**Example:**
```python
# Source: ib_async contract.py + IB TWS API spread docs
from ib_async import Bag, ComboLeg, TagValue, LimitOrder

def build_combo_contract(
    symbol: str,
    legs: list[dict],  # [{conId, ratio, action}, ...]
    exchange: str = "SMART",
    currency: str = "USD",
) -> Bag:
    combo = Bag(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
    )
    combo.comboLegs = [
        ComboLeg(
            conId=leg["conId"],
            ratio=leg["ratio"],
            action=leg["action"],  # "BUY" or "SELL"
            exchange=exchange,
        )
        for leg in legs
    ]
    return combo

# Non-guaranteed combo order (required for SMART-routed spreads)
order = LimitOrder("BUY", 1, net_debit_price)
order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
```

### Pattern 4: Slippage Calculation
**What:** Compare fill price against expected price (mid at time of submission).
**When to use:** On every fill event.
**Example:**
```python
# Slippage = actual_fill_price - expected_price
# For BUY: positive slippage means paid more than expected (bad)
# For SELL: positive slippage means received more than expected (good)
# Normalize: always express as cost (negative = favorable)
def calculate_slippage(
    action: str,
    expected_price: float,
    fill_price: float,
    quantity: float,
) -> float:
    """Return slippage in dollars. Positive = unfavorable."""
    if action == "BUY":
        return (fill_price - expected_price) * quantity
    else:  # SELL
        return (expected_price - fill_price) * quantity
```

### Anti-Patterns to Avoid
- **Bypassing risk gate:** Never call ib.placeOrder() directly from outside OrderExecutionService. Every path must go through submit_order().
- **Polling trade.isDone():** Use event-driven callbacks. Polling blocks the asyncio event loop and is unreliable.
- **Global event handlers for order tracking:** Using ib.orderStatusEvent globally requires complex routing to match events to orders. Per-trade events are cleaner.
- **Forgetting to qualify contracts:** Every contract MUST be qualified (qualifyContractsAsync) before placeOrder. Unqualified contracts cause silent failures or error 200.
- **Hardcoding exchange for combos:** Always use "SMART" for combo legs unless routing to a specific exchange. Mismatched exchanges across legs cause rejections.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Order types | Custom Order() construction | `MarketOrder(action, qty)`, `LimitOrder(action, qty, price)`, `StopOrder(action, qty, price)` | ib_async convenience constructors set orderType and price fields correctly |
| Contract qualification | Manual conId lookup | `ib.qualifyContractsAsync(*contracts)` | Handles all IB validation, fills in conId, multiplier, trading class |
| Combo contracts | Manual Contract(secType="BAG") | `Bag(symbol=..., exchange=..., currency=...)` | Auto-sets secType, cleaner than manual construction |
| Order status tracking | Parsing IB callback strings manually | Existing OrderTracker.handle_ib_status() | Already maps IB status strings to state machine events (Phase 1) |
| State machine | Custom state tracking dict | Existing OrderStateMachine (Phase 1) | Already handles all valid/invalid transitions with TransitionNotAllowed |
| Risk validation | Custom pre-trade checks | `evaluate_with_failsafe(risk_manager, proposal)` | Already wraps all risk checks with timeout and fail-safe (Phase 3) |
| IB margin check | Custom margin calculation | `ib.whatIfOrderAsync(contract, order)` via existing check_margin() | Already implemented in Phase 3 with timeout and UNSET_DOUBLE handling |

**Key insight:** Phase 1 and Phase 3 already built the hardest parts (state machine, risk gate, margin checks). Phase 4's job is wiring them together and adding the IB order placement calls, NOT rebuilding infrastructure.

## Common Pitfalls

### Pitfall 1: Unqualified Contracts Cause Silent Failures
**What goes wrong:** Calling placeOrder() with a contract that hasn't been qualified (conId == 0) causes IB error 200 "No security definition has been found for the request".
**Why it happens:** Developer creates Option() or Bag() and passes it directly to placeOrder() without qualification.
**How to avoid:** Always call `ib.qualifyContractsAsync(contract)` before placeOrder. For combo legs, each individual leg contract must be qualified FIRST (to get conId), then the Bag contract itself does NOT need qualification -- it uses the leg conIds directly.
**Warning signs:** IB error 200, Trade object immediately goes to error state.

### Pitfall 2: Non-Guaranteed Flag Missing on SMART Combos
**What goes wrong:** Combo orders routed via SMART exchange are rejected if the NonGuaranteed flag is not set.
**Why it happens:** IB requires explicit opt-in for non-guaranteed execution of SMART-routed combos.
**How to avoid:** Always add `order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]` for SMART-routed combo orders.
**Warning signs:** Order rejected with error about guaranteed/non-guaranteed routing.

### Pitfall 3: Wrapper State Cleared on Disconnect
**What goes wrong:** After disconnect, `ib.openTrades()` returns empty. Orders placed before disconnect are "orphaned" from the ib_async Trade objects.
**Why it happens:** ib_async's wrapper.reset() clears internal state (trades dict) on disconnect. After reconnect, reqOpenOrders() repopulates, but the old Trade objects and their event subscriptions are gone.
**How to avoid:** (a) Persist all order state to database (already done via OrderTracker), (b) On reconnect, call reqOpenOrdersAsync() to get current open orders, (c) Reconcile DB state with IB state -- match by ib_order_id or ib_perm_id, (d) Create new Trade event subscriptions for recovered orders.
**Warning signs:** Orders show as "SUBMITTED" in DB but no fill events are received after reconnect.

### Pitfall 4: IB Order ID Changes After Reconnect
**What goes wrong:** The orderId assigned by ib_async is session-local. After reconnect, the same underlying IB order may have a different orderId in the API.
**Why it happens:** ib_async assigns orderId via getReqId() which is a session counter. The permanent identifier is permId, which IB assigns and is stable across sessions.
**How to avoid:** Store BOTH ib_order_id AND ib_perm_id in the database Order record (already has fields for both). Use permId for cross-session reconciliation after reconnect. Use orderId only within a session.
**Warning signs:** Cannot find order by orderId after reconnect.

### Pitfall 5: Combo Order Pricing Semantics
**What goes wrong:** Limit price for combo orders represents the NET price (sum of legs considering BUY/SELL directions), not a per-leg price.
**Why it happens:** Misunderstanding IB's combo pricing convention.
**How to avoid:** Combo limit price = Sum of (leg_price * ratio * sign), where sign is +1 for BUY legs and -1 for SELL legs. For a debit spread (buy lower, sell higher): limit price is the net debit. For a credit spread: limit price is the net credit (negative value means you receive credit).
**Warning signs:** IB error 463 "You must enter a valid price".

### Pitfall 6: Partial Fills on Combo Orders
**What goes wrong:** IB may fill combo legs at different times. The Trade object may report partial fills where individual legs are filled but the combo is not fully complete.
**Why it happens:** Non-guaranteed combos allow individual leg execution at different times.
**How to avoid:** Track fills per-leg using the execution details in Fill objects. The Fill.execution.cumQty and Fill.execution.avgPrice fields track cumulative fill state. Use trade.isDone() to determine when the entire combo is complete. Do not assume a single fillEvent means the order is fully filled -- check trade.orderStatus.remaining.
**Warning signs:** Fill count does not match expected quantity, trade.remaining() > 0 after fill event.

### Pitfall 7: structlog 'event' Keyword Conflict
**What goes wrong:** Using `event=` as a structlog keyword argument conflicts with structlog's reserved `event` key.
**Why it happens:** The word "event" is natural when logging order events, but structlog uses it internally for the log message.
**How to avoid:** Use `trigger=` instead of `event=` in structlog calls (established in Phase 1, 01-05 decision).
**Warning signs:** structlog warning about reserved keyword.

## Code Examples

### Creating and Placing a Single-Leg Option Order
```python
# Source: ib_async API + existing codebase patterns
from ib_async import IB, Option, LimitOrder, MarketOrder, StopOrder

# 1. Create and qualify the option contract
contract = Option(
    symbol="AAPL",
    lastTradeDateOrContractMonth="20260417",
    strike=200.0,
    right="C",
    exchange="SMART",
    currency="USD",
)
qualified = await ib.qualifyContractsAsync(contract)
contract = qualified[0]  # Now has conId populated

# 2. Create the order
order = LimitOrder("BUY", 1, 5.50)  # Buy 1 contract at $5.50

# 3. Place the order (returns live-updating Trade)
trade = ib.placeOrder(contract, order)

# trade.order.orderId -> session-local order ID
# trade.order.permId -> will be populated after IB acknowledges
```

### Creating a Multi-Leg Combo (Vertical Spread)
```python
# Source: ib_async Bag/ComboLeg + IB spread docs
from ib_async import IB, Option, Bag, ComboLeg, LimitOrder, TagValue

# 1. Qualify individual leg contracts to get conIds
long_call = Option("AAPL", "20260417", 195.0, "C", "SMART", currency="USD")
short_call = Option("AAPL", "20260417", 200.0, "C", "SMART", currency="USD")
qualified = await ib.qualifyContractsAsync(long_call, short_call)
long_call, short_call = qualified[0], qualified[1]

# 2. Build the Bag contract
combo = Bag(symbol="AAPL", exchange="SMART", currency="USD")
combo.comboLegs = [
    ComboLeg(conId=long_call.conId, ratio=1, action="BUY", exchange="SMART"),
    ComboLeg(conId=short_call.conId, ratio=1, action="SELL", exchange="SMART"),
]

# 3. Create order with NonGuaranteed flag
net_debit = 2.50  # Max willing to pay for the spread
order = LimitOrder("BUY", 1, net_debit)
order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]

# 4. Place
trade = ib.placeOrder(combo, order)
```

### Creating an Iron Condor (4-leg combo)
```python
# Source: ib_async Bag/ComboLeg + IB spread docs
# Iron condor: sell OTM put spread + sell OTM call spread
legs = [
    Option("SPY", "20260417", 490.0, "P", "SMART", currency="USD"),  # buy put (wing)
    Option("SPY", "20260417", 500.0, "P", "SMART", currency="USD"),  # sell put
    Option("SPY", "20260417", 530.0, "C", "SMART", currency="USD"),  # sell call
    Option("SPY", "20260417", 540.0, "C", "SMART", currency="USD"),  # buy call (wing)
]
qualified = await ib.qualifyContractsAsync(*legs)

combo = Bag(symbol="SPY", exchange="SMART", currency="USD")
combo.comboLegs = [
    ComboLeg(conId=qualified[0].conId, ratio=1, action="BUY", exchange="SMART"),
    ComboLeg(conId=qualified[1].conId, ratio=1, action="SELL", exchange="SMART"),
    ComboLeg(conId=qualified[2].conId, ratio=1, action="SELL", exchange="SMART"),
    ComboLeg(conId=qualified[3].conId, ratio=1, action="BUY", exchange="SMART"),
]

# Iron condor is a credit trade -- net credit received
net_credit = 1.80
order = LimitOrder("BUY", 1, net_credit)  # "BUY" the combo at credit
order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]

trade = ib.placeOrder(combo, order)
```

### Subscribing to Trade Events for Fill Tracking
```python
# Source: ib_async Trade object events
def setup_trade_monitoring(trade: Trade, order_id: str, tracker: OrderTracker):
    """Subscribe to a Trade's lifecycle events."""

    async def on_status(t: Trade):
        status = t.orderStatus.status
        await tracker.handle_ib_status(order_id, status)

    async def on_fill(t: Trade, fill):
        # fill.execution has: price, shares, avgPrice, cumQty, side
        # fill.commissionReport has: commission, realizedPNL
        # fill.time has: fill timestamp
        await record_fill(order_id, fill)

    async def on_commission(t: Trade, fill, report):
        # report.commission, report.realizedPNL
        await record_commission(order_id, fill, report)

    trade.statusEvent += on_status
    trade.fillEvent += on_fill
    trade.commissionReportEvent += on_commission
```

### Reconnection Order Recovery
```python
# Source: ib_async reqOpenOrdersAsync + IB open orders docs
async def recover_orders_after_reconnect(
    ib: IB,
    order_tracker: OrderTracker,
    session_factory,
):
    """Reconcile in-flight orders after IB reconnection."""
    # 1. Get current open orders from IB
    open_trades = await ib.reqOpenOrdersAsync()

    # 2. Load in-flight orders from DB (not in terminal state)
    async with get_session(session_factory) as session:
        result = await session.execute(
            select(Order).where(
                Order.current_state.not_in(["FILLED", "CANCELLED", "ERROR"])
            )
        )
        db_orders = result.scalars().all()

    # 3. Reconcile: match by permId
    ib_perm_ids = {t.order.permId: t for t in open_trades if t.order.permId}

    for db_order in db_orders:
        if db_order.ib_perm_id in ib_perm_ids:
            # Order still open in IB -- resubscribe to events
            ib_trade = ib_perm_ids[db_order.ib_perm_id]
            setup_trade_monitoring(ib_trade, db_order.id, order_tracker)
        else:
            # Order not in IB open orders -- check if filled or cancelled
            # Search executions for this permId
            fills = [f for f in ib.fills() if f.execution.permId == db_order.ib_perm_id]
            if fills:
                await order_tracker.handle_ib_status(db_order.id, "Filled")
            else:
                # Assume cancelled if not found anywhere
                await order_tracker.handle_ib_status(db_order.id, "Cancelled")
```

### Cancel Order Flow
```python
# Source: ib_async cancelOrder API
async def cancel_order(
    ib: IB,
    order_tracker: OrderTracker,
    order_id: str,
    ib_order: Order,  # ib_async Order object
):
    """Cancel an open order."""
    # 1. Transition state machine to PENDING_CANCEL
    await order_tracker.transition(order_id, "request_cancel")

    # 2. Send cancel to IB
    trade = ib.cancelOrder(ib_order)

    # Trade events will fire statusEvent -> "Cancelled" or "ApiCancelled"
    # which handle_ib_status will process
    return trade
```

## IB API Key Data Structures Reference

### OrderStatus Constants (from ib_async)
```python
# OrderStatus string values used by IB:
OrderStatus.PendingSubmit = "PendingSubmit"
OrderStatus.PendingCancel = "PendingCancel"
OrderStatus.PreSubmitted = "PreSubmitted"
OrderStatus.Submitted = "Submitted"
OrderStatus.ApiPending = "ApiPending"
OrderStatus.ApiCancelled = "ApiCancelled"
OrderStatus.Cancelled = "Cancelled"
OrderStatus.Filled = "Filled"
OrderStatus.Inactive = "Inactive"

# Terminal states:
OrderStatus.DoneStates = frozenset(["Filled", "Cancelled", "ApiCancelled"])
# Active states:
OrderStatus.ActiveStates = frozenset(["PendingSubmit", "ApiPending", "PreSubmitted", "Submitted"])
```

### Execution Dataclass Fields
```python
@dataclass
class Execution:
    execId: str = ""
    time: datetime = EPOCH
    acctNumber: str = ""
    exchange: str = ""
    side: str = ""         # "BOT" or "SLD"
    shares: float = 0.0    # Shares filled in this execution
    price: float = 0.0     # Price of this execution
    permId: int = 0        # Permanent order ID (stable across sessions)
    clientId: int = 0
    orderId: int = 0
    liquidation: int = 0
    cumQty: float = 0.0    # Cumulative quantity filled
    avgPrice: float = 0.0  # Average fill price so far
    orderRef: str = ""
    lastLiquidity: int = 0 # 1=added, 2=removed, 3=routed out
```

### CommissionReport Dataclass Fields
```python
@dataclass
class CommissionReport:
    execId: str = ""       # Links to Execution.execId
    commission: float = 0.0
    currency: str = ""
    realizedPNL: float = 0.0
    yield_: float = 0.0
    yieldRedemptionDate: int = 0
```

### Fill NamedTuple
```python
class Fill(NamedTuple):
    contract: Contract
    execution: Execution
    commissionReport: CommissionReport
    time: datetime
```

### Trade Object
```python
@dataclass
class Trade:
    contract: Contract
    order: Order
    orderStatus: OrderStatus
    fills: list[Fill]
    log: list[TradeLogEntry]
    # Events:
    #   statusEvent(trade)
    #   fillEvent(trade, fill)
    #   commissionReportEvent(trade, fill, report)
    #   modifyEvent(trade)
    #   cancelEvent(trade)
    #   cancelledEvent(trade)
    #   filledEvent(trade)

    def isActive(self) -> bool: ...
    def isDone(self) -> bool: ...
    def filled(self) -> float: ...     # Quantity filled
    def remaining(self) -> float: ...  # Quantity remaining
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ib_insync | ib_async (fork/rewrite) | 2023-2024 | ib_async is the maintained successor; same API surface, better async support |
| Global orderStatusEvent handler | Per-trade statusEvent/fillEvent | Available since ib_insync | Cleaner per-order tracking, no routing logic needed |
| Manual Order() construction | MarketOrder/LimitOrder/StopOrder constructors | Long-standing | Less error-prone, auto-sets orderType |
| reqOpenOrders (blocking) | openTrades() / reqOpenOrdersAsync() | Available in ib_async | openTrades() is faster (cached); reqOpenOrdersAsync for fresh data |
| current_state.value (deprecated) | current_state_value (python-statemachine v3) | python-statemachine 3.0 | Established in Phase 1 (01-05 decision) |

**Deprecated/outdated:**
- `ib_insync`: Replaced by `ib_async` (same author, ib-api-reloaded org)
- `reqOpenOrders()` blocking: Use `reqOpenOrdersAsync()` or cached `openTrades()`
- `current_state.value`: Use `current_state_value` (python-statemachine v3)

## DB Schema Additions

### ExecutionRecord Table (new)
```python
class ExecutionRecord(Base):
    """Records individual fill executions with slippage tracking."""
    __tablename__ = "execution_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"))
    exec_id: Mapped[str] = mapped_column(String(50), unique=True)  # IB execution ID
    side: Mapped[str] = mapped_column(String(4))  # "BOT" or "SLD"
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    cum_qty: Mapped[float] = mapped_column(Float)
    commission: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exchange: Mapped[str] = mapped_column(String(20))
    liquidity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1=add, 2=remove
    # Slippage tracking
    expected_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    slippage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # In dollars
    slippage_bps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # In basis points
```

### Order Table Additions
The existing Order model already has `ib_order_id`, `ib_perm_id`, `fill_price`, and `filled_quantity` columns. These may need:
- `expected_price` column: mid-market price at time of order submission (for slippage calculation)
- `total_commission` column: accumulated commission across all fills
- `combo_legs` column: JSON field for multi-leg order metadata (optional, for audit)
- `proposal_id` column: links to risk decision audit trail

## Open Questions

1. **Combo order pricing for credit spreads:**
   - What we know: IB combo limit price is the net price of all legs. For credit trades, this should be negative (you receive premium).
   - What's unclear: Whether ib_async's LimitOrder with negative lmtPrice works correctly for credit combos, or if the sign convention requires special handling.
   - Recommendation: Test with paper trading. If negative price is rejected, try positive price with "SELL" action on the combo.

2. **Partial fill handling for combos:**
   - What we know: Non-guaranteed combos can fill legs at different times. The Trade.fillEvent fires per execution.
   - What's unclear: Whether the state machine should transition to a PARTIAL_FILL state or stay in SUBMITTED (current behavior: submitted.to.itself() for partial_fill).
   - Recommendation: Keep current approach -- partial_fill stays in SUBMITTED state. Track partial fills in execution_records table. Only transition to FILLED when trade.isDone().

3. **reqOpenOrdersAsync timing after reconnect:**
   - What we know: ib_async automatically calls reqOpenOrders on connectAsync (when StartupFetch.ORDERS_OPEN flag is set). State is auto-synced after connection.
   - What's unclear: Whether there's a timing window between connection and sync completion where orders might be missed.
   - Recommendation: Wait for connectedEvent before accessing openTrades(). Use a small delay (1-2 seconds) or rely on the connection manager's connected event.

4. **6-leg combo exchange support:**
   - What we know: IB supports up to 6-leg combos, but some exchanges (SPX, CBOE) may not support 6 legs.
   - What's unclear: Exact exchange-specific leg limits for SMART-routed options combos.
   - Recommendation: Design for up to 6 legs. Handle rejection gracefully with clear error messages. For SPX, may need to use ISE or PHLX exchange routing.

## Sources

### Primary (HIGH confidence)
- [ib_async API docs](https://ib-api-reloaded.github.io/ib_async/api.html) - placeOrder, Trade, OrderStatus, Fill, Execution
- [ib_async source: ib.py](https://ib-api-reloaded.github.io/ib_async/_modules/ib_async/ib.html) - placeOrder implementation, cancelOrder, connectAsync
- [ib_async source: contract.py](https://ib-api-reloaded.github.io/ib_async/_modules/ib_async/contract.html) - Contract, Option, Bag, ComboLeg classes
- [ib_async source: objects.py](https://ib-api-reloaded.github.io/ib_async/_modules/ib_async/objects.html) - Fill, Execution, CommissionReport, TradeLogEntry
- [ib_async source: order.py](https://ib-api-reloaded.github.io/ib_async/_modules/ib_async/order.html) - Order, MarketOrder, LimitOrder, StopOrder, OrderStatus
- [IB TWS API: Spread contracts](https://interactivebrokers.github.io/tws-api/spread_contracts.html) - BAG contract, ComboLeg, exchange routing
- [IB TWS API: Open orders](https://interactivebrokers.github.io/tws-api/open_orders.html) - reqOpenOrders, reqAutoOpenOrders, recovery

### Secondary (MEDIUM confidence)
- [ib_async GitHub discussions #80](https://github.com/ib-api-reloaded/ib_async/discussions/80) - Partial fill handling patterns
- [ib_insync issues #130](https://github.com/erdewit/ib_insync/issues/130) - Order recovery after reconnect (library author guidance)
- [IB combo order gist](https://gist.github.com/chadhumphrey/872a9d8d7e1619b974754fc1d9b6fd05) - Combo order implementation example
- [IB TWS API: Basic orders](https://interactivebrokers.github.io/tws-api/basic_orders.html) - Order type definitions

### Tertiary (LOW confidence)
- [Elite Trader: Handling disconnects](https://www.elitetrader.com/et/threads/handling-disconnects-when-using-the-ib-api.11059/) - Community discussion on disconnect recovery
- [QuestDB: Execution slippage measurement](https://questdb.com/glossary/execution-slippage-measurement/) - Slippage calculation methodology

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new dependencies; all ib_async APIs verified via official docs and source code
- Architecture: HIGH - Patterns derived from existing codebase (Phase 1-3) plus verified ib_async API
- Order placement API: HIGH - placeOrder, MarketOrder/LimitOrder/StopOrder verified from ib_async source
- Combo/BAG contracts: HIGH - Bag, ComboLeg, TagValue verified from ib_async source and IB TWS docs
- Fill tracking: HIGH - Trade events, Fill, Execution, CommissionReport verified from ib_async source
- Reconnection recovery: MEDIUM - Pattern derived from library author guidance and IB docs; timing nuances may need runtime validation
- Combo pricing semantics: MEDIUM - Verified net pricing model, but credit spread sign convention needs paper trade validation
- 6-leg exchange limits: LOW - Known limitation mentioned in IB docs but specific exchange constraints not fully documented

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (30 days - stable domain, ib_async API is mature)
