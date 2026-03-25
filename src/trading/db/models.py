"""SQLAlchemy ORM models for the trading system.

Defines the core persistence models for order tracking and state transitions.
OrderStateTransition is designed to be a TimescaleDB hypertable partitioned
by timestamp for efficient time-series queries.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
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

    state_transitions: Mapped[list["OrderStateTransition"]] = relationship(
        "OrderStateTransition", back_populates="order", lazy="selectin"
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
