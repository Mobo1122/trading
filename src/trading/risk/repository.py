"""Risk repository for persisting decisions and circuit breaker state.

Provides async database operations for:
- Saving risk evaluation decisions (approve/reject log)
- Upserting circuit breaker state (halt status + loss accumulators)
- Loading circuit breaker state on startup for crash recovery
"""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from trading.db.models import CircuitBreakerState, RiskDecisionRecord
from trading.db.session import get_session
from trading.risk.models import RiskDecision


log = structlog.get_logger().bind(component="risk_repository")


class RiskRepository:
    """Async repository for risk engine persistence.

    Uses the shared async SQLAlchemy session factory from Phase 1.
    All writes go through the get_session context manager which handles
    commit/rollback/close automatically.

    Args:
        session_factory: An async_sessionmaker instance for creating sessions.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def save_decision(self, decision: RiskDecision, mode: str) -> None:
        """Persist a risk evaluation decision to the database.

        Maps all RiskDecision fields including nested MarginResult subfields
        into a flat RiskDecisionRecord row.

        Args:
            decision: The risk evaluation result to persist.
            mode: Trading mode ('paper' or 'live').
        """
        record = RiskDecisionRecord(
            proposal_id=decision.proposal_id,
            approved=decision.approved,
            violated_rule=(
                decision.violated_rule.value if decision.violated_rule else None
            ),
            details=decision.details or None,
            max_loss=None,
            dry_run=decision.dry_run,
            mode=mode,
            margin_init_after=(
                decision.margin_result.init_margin_after
                if decision.margin_result
                else None
            ),
            margin_maint_after=(
                decision.margin_result.maint_margin_after
                if decision.margin_result
                else None
            ),
            equity_with_loan_after=(
                decision.margin_result.equity_with_loan_after
                if decision.margin_result
                else None
            ),
            estimated_commission=(
                decision.margin_result.commission
                if decision.margin_result
                else None
            ),
            margin_warning=(
                decision.margin_result.warning_text
                if decision.margin_result
                else None
            ),
            margin_check_timed_out=(
                decision.margin_result.timed_out
                if decision.margin_result
                else False
            ),
        )

        async with get_session(self._session_factory) as session:
            session.add(record)

        log.debug(
            "Risk decision saved",
            proposal_id=decision.proposal_id,
            approved=decision.approved,
            mode=mode,
        )

    async def save_circuit_breaker_state(
        self,
        mode: str,
        halt_type: str,
        halted: bool,
        halted_at: datetime | None,
        daily_loss: float,
        weekly_loss: float,
    ) -> None:
        """Upsert circuit breaker state to the database.

        Uses session.merge() to insert or update based on the unique
        constraint on (mode, halt_type). This ensures exactly one row
        per breaker survives across restarts.

        Args:
            mode: Trading mode ('paper' or 'live').
            halt_type: Breaker type ('daily' or 'weekly').
            halted: Whether the breaker is currently tripped.
            halted_at: UTC timestamp when halt was activated, or None.
            daily_loss: Current daily realized loss accumulator.
            weekly_loss: Current weekly realized loss accumulator.
        """
        async with get_session(self._session_factory) as session:
            # Load existing record to get its id for merge, or create new
            stmt = select(CircuitBreakerState).where(
                CircuitBreakerState.mode == mode,
                CircuitBreakerState.halt_type == halt_type,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.halted = halted
                existing.halted_at = halted_at
                existing.daily_realized_loss = daily_loss
                existing.weekly_realized_loss = weekly_loss
            else:
                record = CircuitBreakerState(
                    mode=mode,
                    halt_type=halt_type,
                    halted=halted,
                    halted_at=halted_at,
                    daily_realized_loss=daily_loss,
                    weekly_realized_loss=weekly_loss,
                )
                session.add(record)

        log.debug(
            "Circuit breaker state saved",
            mode=mode,
            halt_type=halt_type,
            halted=halted,
            daily_loss=daily_loss,
            weekly_loss=weekly_loss,
        )

    async def load_circuit_breaker_state(
        self, mode: str
    ) -> list[CircuitBreakerState]:
        """Load all circuit breaker state records for a trading mode.

        Returns both daily and weekly breaker rows (if they exist) so the
        CircuitBreaker can restore halt state into Redis on startup.

        Args:
            mode: Trading mode ('paper' or 'live').

        Returns:
            List of CircuitBreakerState ORM objects for the given mode.
        """
        async with get_session(self._session_factory) as session:
            stmt = select(CircuitBreakerState).where(
                CircuitBreakerState.mode == mode
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())

        log.debug(
            "Circuit breaker state loaded",
            mode=mode,
            records=len(rows),
        )
        return rows
