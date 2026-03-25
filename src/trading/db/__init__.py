"""Database layer for the trading system.

Exports:
    Base: SQLAlchemy declarative base for all models.
    Order: Order persistence model.
    OrderState: Enum of valid order states.
    OrderStateTransition: Audit log model for state changes.
    create_db_engine: Factory for async SQLAlchemy engines.
    create_session_factory: Factory for async session makers.
    get_session: Async context manager for database sessions.
"""

from trading.db.engine import create_db_engine, create_session_factory
from trading.db.models import Base, Order, OrderState, OrderStateTransition
from trading.db.session import get_session

__all__ = [
    "Base",
    "Order",
    "OrderState",
    "OrderStateTransition",
    "create_db_engine",
    "create_session_factory",
    "get_session",
]
