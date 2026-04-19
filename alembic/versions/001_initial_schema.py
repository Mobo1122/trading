"""Initial schema: orders and order_state_transitions tables.

Creates the core order tracking tables with TimescaleDB hypertable
for order_state_transitions to enable efficient time-series queries.

Revision ID: 001
Revises: None
Create Date: 2026-03-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create orders and order_state_transitions tables.

    The order_state_transitions table is converted to a TimescaleDB
    hypertable partitioned by the timestamp column for efficient
    time-range queries over the state transition audit log.
    """
    # -- orders table --
    op.create_table(
        "orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("sec_type", sa.String(10), nullable=False),
        sa.Column("action", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("order_type", sa.String(10), nullable=False),
        sa.Column("limit_price", sa.Float, nullable=True),
        sa.Column("stop_price", sa.Float, nullable=True),
        sa.Column("current_state", sa.String(20), nullable=False, server_default="CREATED"),
        sa.Column("ib_order_id", sa.Integer, nullable=True),
        sa.Column("ib_perm_id", sa.Integer, nullable=True),
        sa.Column("fill_price", sa.Float, nullable=True),
        sa.Column("filled_quantity", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # -- order_state_transitions table --
    op.create_table(
        "order_state_transitions",
        sa.Column("id", sa.Integer, autoincrement=True, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Composite PK includes timestamp so TimescaleDB can partition as hypertable
        sa.PrimaryKeyConstraint("id", "timestamp"),
        sa.Column(
            "order_id",
            sa.String(36),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(20), nullable=True),
        sa.Column("to_state", sa.String(20), nullable=False),
        sa.Column("event", sa.String(50), nullable=False),
        sa.Column("details", sa.String, nullable=True),
    )

    # Index on timestamp (for hypertable range queries)
    op.create_index(
        "ix_order_state_transitions_timestamp",
        "order_state_transitions",
        ["timestamp"],
    )

    # Composite index on (order_id, timestamp) for per-order lookups
    op.create_index(
        "ix_order_state_transitions_order_id_timestamp",
        "order_state_transitions",
        ["order_id", "timestamp"],
    )

    # Convert order_state_transitions to a TimescaleDB hypertable.
    # This MUST be in the same migration as table creation (before any data).
    op.execute(
        "SELECT create_hypertable('order_state_transitions', 'timestamp')"
    )


def downgrade() -> None:
    """Drop order_state_transitions and orders tables."""
    op.drop_table("order_state_transitions")
    op.drop_table("orders")
