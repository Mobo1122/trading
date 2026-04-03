"""RiskManager orchestrator -- single entry point for all trade risk evaluation.

Chains all evaluators in order with short-circuit on first violation:
1. Emergency halt
2. Circuit breaker auto-reset
3. Circuit breaker check
4. Position sizing
5. Greeks exposure
6. Strategy restrictions
7. Margin check (via IB whatIfOrder)

The evaluate_with_failsafe module-level function wraps check_trade with
a timeout, ensuring no trade can proceed without explicit approval (RISK-05).

Every decision (approved or rejected, dry-run or real) is persisted to the
database for full audit trail.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from trading.risk.circuit_breaker import CircuitBreaker
from trading.risk.config import RiskLimitsProfile
from trading.risk.evaluators import evaluate_position_size, evaluate_strategy_restrictions
from trading.risk.greeks import PortfolioGreeks, evaluate_greeks_exposure
from trading.risk.margin_check import check_margin, evaluate_margin
from trading.risk.models import (
    MarginResult,
    RiskDecision,
    TradeLeg,
    TradeProposal,
    ViolatedRule,
)
from trading.risk.repository import RiskRepository


log = structlog.get_logger().bind(component="risk_manager")


class RiskManager:
    """Orchestrates all risk evaluators for trade proposal evaluation.

    The single public API for risk checks. Phase 4 (execution) and Phase 5
    (agents) call check_trade() for every trade proposal. All decisions are
    persisted for audit regardless of dry_run flag.

    Args:
        limits: Active RiskLimitsProfile for the current trading mode.
        circuit_breaker: CircuitBreaker instance for loss limit enforcement.
        repository: RiskRepository for persisting decisions.
        ib: Optional IB instance for margin checks (None if not connected).
        mode: Trading mode ('paper' or 'live').
    """

    def __init__(
        self,
        limits: RiskLimitsProfile,
        circuit_breaker: CircuitBreaker,
        repository: RiskRepository,
        ib: Any | None = None,
        mode: str = "paper",
    ) -> None:
        self._limits = limits
        self._circuit_breaker = circuit_breaker
        self._repository = repository
        self._ib = ib
        self._mode = mode

    async def check_trade(
        self,
        proposal: TradeProposal,
        dry_run: bool = False,
        current_portfolio_greeks: PortfolioGreeks | None = None,
        existing_positions: list[TradeLeg] | None = None,
    ) -> RiskDecision:
        """Evaluate a trade proposal against all risk rules.

        Runs the evaluator chain in order, short-circuiting on the first
        violation. If all checks pass, returns an approved decision.

        Evaluator order:
        1. Emergency halt check
        2. Circuit breaker auto-reset
        3. Circuit breaker check (daily/weekly loss limits)
        4. Position sizing (dollars, contracts, portfolio %)
        5. Greeks exposure (delta, gamma, theta, vega)
        6. Strategy restrictions (allowlist, naked options)
        7. Margin check (IB whatIfOrder, only if IB connected)

        Every decision is persisted to the database for audit.

        Args:
            proposal: Trade request to evaluate.
            dry_run: If True, decision is logged but flagged as non-enforced.
            current_portfolio_greeks: Current portfolio Greeks for exposure check.
            existing_positions: Current positions for naked options detection.

        Returns:
            RiskDecision with approved=True if all checks pass, or
            approved=False with the first violated rule.
        """
        # 1. Emergency halt check
        if self._limits.emergency_halt:
            decision = RiskDecision(
                approved=False,
                violated_rule=ViolatedRule.EMERGENCY_HALT,
                details="Emergency halt is active -- all trading suspended",
                proposal_id=proposal.proposal_id,
                dry_run=dry_run,
            )
            await self._persist(decision)
            return decision

        # 2. Auto-reset check (handles market-open resets)
        await self._circuit_breaker.check_and_reset()

        # 3. Circuit breaker check
        cb_result = await self._circuit_breaker.check()
        if cb_result is not None:
            cb_result.proposal_id = proposal.proposal_id
            cb_result.dry_run = dry_run
            await self._persist(cb_result)
            return cb_result

        # 4. Position sizing
        pos_result = evaluate_position_size(proposal, self._limits.position)
        if pos_result is not None:
            pos_result.dry_run = dry_run
            await self._persist(pos_result)
            return pos_result

        # 5. Greeks exposure
        greeks_result = evaluate_greeks_exposure(
            proposal, self._limits.greeks, current_portfolio_greeks
        )
        if greeks_result is not None:
            greeks_result.dry_run = dry_run
            await self._persist(greeks_result)
            return greeks_result

        # 6. Strategy restrictions
        strategy_result = evaluate_strategy_restrictions(
            proposal, self._limits.strategy, existing_positions
        )
        if strategy_result is not None:
            strategy_result.dry_run = dry_run
            await self._persist(strategy_result)
            return strategy_result

        # 7. Margin check (only if IB connected and legs have contract/order)
        margin_result = await self._check_margin_if_available(proposal)

        if margin_result is not None:
            margin_eval = evaluate_margin(margin_result, proposal.account_value)
            if margin_eval is not None:
                margin_eval.proposal_id = proposal.proposal_id
                margin_eval.dry_run = dry_run
                await self._persist(margin_eval)
                return margin_eval

        # All checks passed
        decision = RiskDecision(
            approved=True,
            proposal_id=proposal.proposal_id,
            dry_run=dry_run,
            margin_result=margin_result,
        )

        await self._persist(decision)
        return decision

    async def _check_margin_if_available(
        self, proposal: TradeProposal
    ) -> MarginResult | None:
        """Run margin check for each leg that has contract and order data.

        Only runs if self._ib is set (IB connected). Checks each leg
        individually; returns the first margin result (per-leg approach
        per RESEARCH.md recommendation).

        Args:
            proposal: Trade proposal with legs to check.

        Returns:
            MarginResult from the first leg with contract/order, or None.
        """
        if self._ib is None:
            return None

        for leg in proposal.legs:
            if leg.contract is not None and leg.order is not None:
                result = await check_margin(
                    self._ib,
                    leg.contract,
                    leg.order,
                    self._limits.margin_check_timeout,
                )
                return result

        return None

    async def _persist(self, decision: RiskDecision) -> None:
        """Persist a risk decision and log the outcome.

        Args:
            decision: The risk evaluation result to save and log.
        """
        try:
            await self._repository.save_decision(decision, self._mode)
        except Exception:
            log.warning(
                "Failed to persist risk decision",
                proposal_id=decision.proposal_id,
                exc_info=True,
            )

        if decision.approved:
            log.info(
                "Trade approved",
                proposal_id=decision.proposal_id,
                dry_run=decision.dry_run,
                mode=self._mode,
            )
        else:
            log.warning(
                "Trade rejected",
                proposal_id=decision.proposal_id,
                violated_rule=(
                    decision.violated_rule.value
                    if decision.violated_rule
                    else None
                ),
                details=decision.details,
                dry_run=decision.dry_run,
                mode=self._mode,
            )


async def evaluate_with_failsafe(
    risk_manager: RiskManager,
    proposal: TradeProposal,
    timeout: float = 10.0,
    **kwargs: Any,
) -> RiskDecision:
    """Fail-safe wrapper around RiskManager.check_trade.

    Guarantees a trade is NEVER submitted without an explicit decision.
    On ANY exception (timeout, runtime error, connection failure, etc.),
    returns a rejection with RISK_MANAGER_UNAVAILABLE.

    This enforces RISK-05: if the risk manager is unreachable or broken,
    all trades are blocked.

    Args:
        risk_manager: RiskManager instance to evaluate with.
        proposal: Trade proposal to evaluate.
        timeout: Maximum seconds for the entire evaluation (default 10.0).
        **kwargs: Additional arguments passed to check_trade (dry_run, etc).

    Returns:
        RiskDecision -- always. Either the real evaluation result or a
        RISK_MANAGER_UNAVAILABLE rejection on any failure.
    """
    try:
        return await asyncio.wait_for(
            risk_manager.check_trade(proposal, **kwargs),
            timeout=timeout,
        )
    except Exception:
        log.warning(
            "Risk manager evaluation failed or timed out",
            proposal_id=proposal.proposal_id,
            exc_info=True,
        )
        return RiskDecision(
            approved=False,
            violated_rule=ViolatedRule.RISK_MANAGER_UNAVAILABLE,
            details="Risk manager evaluation failed or timed out",
            proposal_id=proposal.proposal_id,
        )
