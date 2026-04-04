"""SQLAlchemy ORM models for the trading system.

Defines the core persistence models for order tracking and state transitions.
OrderStateTransition is designed to be a TimescaleDB hypertable partitioned
by timestamp for efficient time-series queries.
"""

from __future__ import annotations

import datetime as dt
import enum
from datetime import datetime
from typing import Optional
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class OrderState(str, enum.Enum):
    """Valid states for an order throughout its lifecycle.

    State flow:
        CREATED -> API_PENDING -> PENDING_SUBMIT -> PRE_SUBMITTED
        -> SUBMITTED -> FILLED | CANCELLED | ERROR
        SUBMITTED -> PENDING_CANCEL -> CANCELLED | ERROR
    """

    CREATED = "CREATED"
    API_PENDING = "API_PENDING"
    PENDING_SUBMIT = "PENDING_SUBMIT"
    PRE_SUBMITTED = "PRE_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    PENDING_CANCEL = "PENDING_CANCEL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class Order(Base):
    """Persistent order record tracking an order through its lifecycle.

    Each order has a unique UUID, instrument details, and state. State
    transitions are tracked separately in OrderStateTransition for a
    full audit trail.
    """

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    sec_type: Mapped[str] = mapped_column(String(10), nullable=False)
    action: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    order_type: Mapped[str] = mapped_column(String(10), nullable=False)
    limit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrderState.CREATED.value
    )
    ib_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ib_perm_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    filled_quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Phase 4: Order execution columns
    expected_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_commission: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    combo_legs: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    proposal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    state_transitions: Mapped[list["OrderStateTransition"]] = relationship(
        "OrderStateTransition", back_populates="order", lazy="selectin"
    )
    execution_records: Mapped[list["ExecutionRecord"]] = relationship(
        "ExecutionRecord", back_populates="order", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<Order(id={self.id!r}, symbol={self.symbol!r}, "
            f"action={self.action!r}, state={self.current_state!r})>"
        )


class OrderStateTransition(Base):
    """Audit log of order state changes.

    Stored as a TimescaleDB hypertable partitioned by timestamp for
    efficient time-range queries. Each row records a single state
    transition with the triggering event and optional details.
    """

    __tablename__ = "order_state_transitions"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=False
    )
    from_state: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    order: Mapped["Order"] = relationship(
        "Order", back_populates="state_transitions"
    )

    __table_args__ = (
        Index("ix_order_state_transitions_order_id_timestamp", "order_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<OrderStateTransition(order_id={self.order_id!r}, "
            f"{self.from_state!r} -> {self.to_state!r}, event={self.event!r})>"
        )


# ---------------------------------------------------------------------------
# Market data ORM models (Phase 2)
# ---------------------------------------------------------------------------


class MarketQuote(Base):
    """Persisted market quote snapshots.

    Stored as a TimescaleDB hypertable partitioned by timestamp
    for efficient time-range queries over quote history.
    """

    __tablename__ = "market_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    con_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sec_type: Mapped[str] = mapped_column(String(10), nullable=False, default="STK")
    bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ask: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_interest: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    implied_volatility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_market_quotes_symbol_ts", "symbol", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<MarketQuote(symbol={self.symbol!r}, "
            f"bid={self.bid}, ask={self.ask}, ts={self.timestamp})>"
        )


class OptionGreeks(Base):
    """Persisted option Greeks snapshots.

    Stored as a TimescaleDB hypertable partitioned by timestamp
    for time-series analysis of Greeks evolution.
    """

    __tablename__ = "option_greeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    con_id: Mapped[int] = mapped_column(Integer, nullable=False)
    implied_vol: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gamma: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    theta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vega: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    und_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_option_greeks_symbol_ts", "symbol", "timestamp"),
        Index("ix_option_greeks_con_id_ts", "con_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<OptionGreeks(symbol={self.symbol!r}, "
            f"delta={self.delta}, iv={self.implied_vol}, ts={self.timestamp})>"
        )


class IVHistory(Base):
    """Daily implied volatility history.

    Stored as a TimescaleDB hypertable partitioned by timestamp
    for efficient IV rank/percentile calculations over time.
    """

    __tablename__ = "iv_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    iv_close: Mapped[float] = mapped_column(Float, nullable=False)
    iv_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iv_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_iv_history_symbol_ts", "symbol", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<IVHistory(symbol={self.symbol!r}, "
            f"iv_close={self.iv_close}, ts={self.timestamp})>"
        )


class EarningsEvent(Base):
    """Upcoming and historical earnings events.

    Regular table (not a hypertable) since earnings data is not
    high-frequency time-series. Unique constraint prevents
    duplicate entries per symbol/date.
    """

    __tablename__ = "earnings_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    earnings_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    hour: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    eps_estimate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    revenue_estimate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint("symbol", "earnings_date", name="uq_earnings_symbol_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<EarningsEvent(symbol={self.symbol!r}, "
            f"date={self.earnings_date}, hour={self.hour!r})>"
        )


# ---------------------------------------------------------------------------
# Risk engine ORM models (Phase 3)
# ---------------------------------------------------------------------------


class RiskDecisionRecord(Base):
    """Persistent log of every risk evaluation decision.

    Records whether each trade proposal was approved or rejected,
    the violated rule (if rejected), margin check results, and
    whether the evaluation was in dry-run mode.
    """

    __tablename__ = "risk_decisions"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approved: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    violated_rule: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    details: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    strategy_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    max_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dry_run: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    margin_init_after: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    margin_maint_after: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    equity_with_loan_after: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    estimated_commission: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    margin_warning: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    margin_check_timed_out: Mapped[bool] = mapped_column(
        sa.Boolean, default=False
    )

    __table_args__ = (
        Index("ix_risk_decisions_ts", "timestamp"),
        Index("ix_risk_decisions_proposal", "proposal_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<RiskDecisionRecord(proposal_id={self.proposal_id!r}, "
            f"approved={self.approved}, rule={self.violated_rule!r})>"
        )


class CircuitBreakerState(Base):
    """Tracks circuit breaker state per mode and halt type.

    Each row represents one circuit breaker (e.g., paper/daily,
    live/weekly). The unique constraint on (mode, halt_type) ensures
    exactly one row per breaker. Loss accumulators reset on period
    boundaries.
    """

    __tablename__ = "circuit_breaker_state"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    halt_type: Mapped[str] = mapped_column(String(10), nullable=False)
    halted: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    halted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    daily_realized_loss: Mapped[float] = mapped_column(
        Float, default=0.0
    )
    weekly_realized_loss: Mapped[float] = mapped_column(
        Float, default=0.0
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint("mode", "halt_type", name="uq_cb_mode_halt_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<CircuitBreakerState(mode={self.mode!r}, "
            f"halt_type={self.halt_type!r}, halted={self.halted})>"
        )


# ---------------------------------------------------------------------------
# Order execution ORM models (Phase 4)
# ---------------------------------------------------------------------------


class ExecutionRecord(Base):
    """Records individual fill executions with slippage tracking.

    Each row represents a single fill event from IB, linked to the parent
    Order. Tracks fill price, cumulative average, commission, and slippage
    relative to the expected mid-market price at submission time.
    """

    __tablename__ = "execution_records"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=False
    )
    exec_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    cum_qty: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    liquidity: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    expected_price: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    slippage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    slippage_bps: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    order: Mapped["Order"] = relationship(
        "Order", back_populates="execution_records"
    )

    __table_args__ = (
        Index("ix_execution_records_order_id", "order_id"),
        Index("ix_execution_records_ts", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<ExecutionRecord(exec_id={self.exec_id!r}, "
            f"order_id={self.order_id!r}, price={self.price}, "
            f"qty={self.quantity}, side={self.side!r})>"
        )
