"""Execution records schema: execution_records table and Order column additions.

Creates the execution_records table for tracking individual fill executions
with slippage data. Adds expected_price, total_commission, combo_legs, and
proposal_id columns to the existing orders table.

Revision ID: 004
Revises: 003
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, Sequence[str], None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create execution_records table and add columns to orders.

    Tables created:
    - execution_records: Individual fill execution tracking with slippage

    Columns added to orders:
    - expected_price: Mid-market price at submission time
    - total_commission: Accumulated commission across all fills
    - combo_legs: JSON text for multi-leg order metadata
    - proposal_id: Links to risk decision audit trail
    """
    # -- execution_records table --
    op.create_table(
        "execution_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "order_id",
            sa.String(36),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column("exec_id", sa.String(50), unique=True, nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("avg_price", sa.Float, nullable=False),
        sa.Column("cum_qty", sa.Float, nullable=False),
        sa.Column("commission", sa.Float, nullable=True),
        sa.Column("realized_pnl", sa.Float, nullable=True),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("liquidity", sa.Integer, nullable=True),
        sa.Column("expected_price", sa.Float, nullable=True),
        sa.Column("slippage", sa.Float, nullable=True),
        sa.Column("slippage_bps", sa.Float, nullable=True),
    )

    op.create_index(
        "ix_execution_records_order_id",
        "execution_records",
        ["order_id"],
    )

    op.create_index(
        "ix_execution_records_ts",
        "execution_records",
        ["timestamp"],
    )

    # -- Add columns to orders table --
    op.add_column(
        "orders",
        sa.Column("expected_price", sa.Float, nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("total_commission", sa.Float, nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("combo_legs", sa.String, nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("proposal_id", sa.String(36), nullable=True),
    )


def downgrade() -> None:
    """Drop execution_records table and remove added columns from orders."""
    op.drop_column("orders", "proposal_id")
    op.drop_column("orders", "combo_legs")
    op.drop_column("orders", "total_commission")
    op.drop_column("orders", "expected_price")
    op.drop_table("execution_records")
