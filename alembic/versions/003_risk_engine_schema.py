"""Risk engine schema: risk_decisions and circuit_breaker_state tables.

Creates the persistence layer for risk evaluation audit logging and
circuit breaker state tracking. Both are regular tables (not hypertables)
since risk decisions are low-frequency events.

Revision ID: 003
Revises: 002
Create Date: 2026-04-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, Sequence[str], None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create risk engine tables.

    Tables created:
    - risk_decisions: Audit log of every trade proposal evaluation
    - circuit_breaker_state: Per-mode/halt-type circuit breaker tracking
    """
    # -- risk_decisions table --
    op.create_table(
        "risk_decisions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column("approved", sa.Boolean, nullable=False),
        sa.Column("violated_rule", sa.String(50), nullable=True),
        sa.Column("details", sa.String, nullable=True),
        sa.Column("strategy_type", sa.String(50), nullable=True),
        sa.Column("max_loss", sa.Float, nullable=True),
        sa.Column("dry_run", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("margin_init_after", sa.Float, nullable=True),
        sa.Column("margin_maint_after", sa.Float, nullable=True),
        sa.Column("equity_with_loan_after", sa.Float, nullable=True),
        sa.Column("estimated_commission", sa.Float, nullable=True),
        sa.Column("margin_warning", sa.String, nullable=True),
        sa.Column(
            "margin_check_timed_out",
            sa.Boolean,
            server_default=sa.text("false"),
        ),
    )

    op.create_index(
        "ix_risk_decisions_ts",
        "risk_decisions",
        ["timestamp"],
    )

    op.create_index(
        "ix_risk_decisions_proposal",
        "risk_decisions",
        ["proposal_id"],
    )

    # -- circuit_breaker_state table --
    op.create_table(
        "circuit_breaker_state",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("halt_type", sa.String(10), nullable=False),
        sa.Column("halted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("halted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_realized_loss", sa.Float, server_default=sa.text("0.0")),
        sa.Column("weekly_realized_loss", sa.Float, server_default=sa.text("0.0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("mode", "halt_type", name="uq_cb_mode_halt_type"),
    )


def downgrade() -> None:
    """Drop risk engine tables in reverse order."""
    op.drop_table("circuit_breaker_state")
    op.drop_table("risk_decisions")
