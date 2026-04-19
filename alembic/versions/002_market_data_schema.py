"""Market data schema: quotes, greeks, IV history, and earnings tables.

Creates the market data persistence layer with TimescaleDB hypertables
for time-series data (market_quotes, option_greeks, iv_history) and a
regular table for earnings events.

Revision ID: 002
Revises: 001
Create Date: 2026-04-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, Sequence[str], None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create market data tables with TimescaleDB hypertables.

    Tables created:
    - market_quotes (hypertable): Real-time quote snapshots
    - option_greeks (hypertable): Option Greeks time-series
    - iv_history (hypertable): Daily IV history for rank/percentile
    - earnings_events (regular): Earnings calendar data
    """
    # -- market_quotes table --
    op.create_table(
        "market_quotes",
        sa.Column("id", sa.Integer, autoincrement=True, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("con_id", sa.Integer, nullable=False),
        sa.Column("sec_type", sa.String(10), nullable=False, server_default="STK"),
        sa.Column("bid", sa.Float, nullable=True),
        sa.Column("ask", sa.Float, nullable=True),
        sa.Column("last", sa.Float, nullable=True),
        sa.Column("volume", sa.Float, nullable=True),
        sa.Column("open_interest", sa.Float, nullable=True),
        sa.Column("implied_volatility", sa.Float, nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    op.create_index(
        "ix_market_quotes_symbol_ts",
        "market_quotes",
        ["symbol", "timestamp"],
    )

    # Convert to TimescaleDB hypertable
    op.execute("SELECT create_hypertable('market_quotes', 'timestamp')")

    # -- option_greeks table --
    op.create_table(
        "option_greeks",
        sa.Column("id", sa.Integer, autoincrement=True, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("con_id", sa.Integer, nullable=False),
        sa.Column("implied_vol", sa.Float, nullable=True),
        sa.Column("delta", sa.Float, nullable=True),
        sa.Column("gamma", sa.Float, nullable=True),
        sa.Column("theta", sa.Float, nullable=True),
        sa.Column("vega", sa.Float, nullable=True),
        sa.Column("und_price", sa.Float, nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    op.create_index(
        "ix_option_greeks_symbol_ts",
        "option_greeks",
        ["symbol", "timestamp"],
    )

    op.create_index(
        "ix_option_greeks_con_id_ts",
        "option_greeks",
        ["con_id", "timestamp"],
    )

    # Convert to TimescaleDB hypertable
    op.execute("SELECT create_hypertable('option_greeks', 'timestamp')")

    # -- iv_history table --
    op.create_table(
        "iv_history",
        sa.Column("id", sa.Integer, autoincrement=True, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("iv_close", sa.Float, nullable=False),
        sa.Column("iv_high", sa.Float, nullable=True),
        sa.Column("iv_low", sa.Float, nullable=True),
        sa.Column("hv_close", sa.Float, nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    op.create_index(
        "ix_iv_history_symbol_ts",
        "iv_history",
        ["symbol", "timestamp"],
    )

    # Convert to TimescaleDB hypertable
    op.execute("SELECT create_hypertable('iv_history', 'timestamp')")

    # -- earnings_events table (regular, NOT a hypertable) --
    op.create_table(
        "earnings_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("earnings_date", sa.Date, nullable=False),
        sa.Column("hour", sa.String(10), nullable=True),
        sa.Column("eps_estimate", sa.Float, nullable=True),
        sa.Column("revenue_estimate", sa.Float, nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("symbol", "earnings_date", name="uq_earnings_symbol_date"),
    )


def downgrade() -> None:
    """Drop all market data tables in reverse order."""
    op.drop_table("earnings_events")
    op.drop_table("iv_history")
    op.drop_table("option_greeks")
    op.drop_table("market_quotes")
