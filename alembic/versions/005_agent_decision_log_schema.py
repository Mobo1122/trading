"""Agent decision log schema: agent_decision_log table.

Creates the agent_decision_log table for audit trail persistence of
every agent decision in the pipeline. Records input, output, reasoning,
message history, token usage, and timing for post-hoc analysis.

Revision ID: 005
Revises: 004
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, Sequence[str], None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agent_decision_log table.

    Tables created:
    - agent_decision_log: Audit trail for every agent run in the pipeline

    Indexes:
    - run_id: Query all decisions within a pipeline run
    - (agent_name, timestamp): Query decisions by agent over time
    - timestamp: Time-range queries across all agents
    """
    op.create_table(
        "agent_decision_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("agent_name", sa.String(20), nullable=False),
        sa.Column("stage_order", sa.Integer, nullable=False),
        sa.Column("input_summary", sa.String, nullable=True),
        sa.Column("output_summary", sa.String, nullable=True),
        sa.Column("reasoning", sa.String, nullable=True),
        sa.Column("messages_json", sa.String, nullable=True),
        sa.Column("output_json", sa.String, nullable=True),
        sa.Column("request_tokens", sa.Integer, nullable=True),
        sa.Column("response_tokens", sa.Integer, nullable=True),
        sa.Column("model_name", sa.String(50), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("error", sa.String, nullable=True),
    )

    op.create_index(
        "ix_agent_decision_log_run_id",
        "agent_decision_log",
        ["run_id"],
    )

    op.create_index(
        "ix_agent_decision_log_agent_ts",
        "agent_decision_log",
        ["agent_name", "timestamp"],
    )

    op.create_index(
        "ix_agent_decision_log_ts",
        "agent_decision_log",
        ["timestamp"],
    )


def downgrade() -> None:
    """Drop agent_decision_log table."""
    op.drop_table("agent_decision_log")
