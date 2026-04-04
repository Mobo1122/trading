"""Expiration monitoring and option position rolling logic.

Identifies option positions approaching expiry by querying IB positions,
evaluates rolling criteria (DTE threshold, unrealized P&L, max loss
multiple), and generates rolling decisions with close+open proposal pairs.

Rolling decisions are deterministic -- the LLM is used only for downstream
execution through the existing pipeline. This module produces serializable
dicts that flow into ``PipelineState.rolling_candidates`` and
``PipelineState.rolling_decisions``.

Pipeline integration:
    The ``ExpirationMonitor`` is invoked at the start of a pipeline run
    (or on a separate schedule). Scan results populate PipelineState
    rolling fields, and downstream agents can execute the close/open
    proposals through the existing risk gate and order execution path.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import structlog
from pydantic import BaseModel, Field

from trading.agents.config import RollingConfig

logger = structlog.get_logger(component="rolling")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RollingCandidate(BaseModel):
    """An option position identified as a rolling candidate.

    Captures all relevant position data needed to evaluate whether
    rolling is appropriate: symbol, expiry, DTE, position direction,
    cost basis, current value, and unrealized P&L.

    Attributes:
        symbol: Underlying symbol (e.g., "SPY").
        con_id: IB contract ID for the option position.
        current_expiry: Expiration date in YYYYMMDD format.
        days_to_expiry: Calendar days until expiration.
        position_size: Signed quantity (positive=long, negative=short).
        avg_cost: Average cost basis per contract.
        current_value: Current market value from portfolio() (None if
            unavailable).
        unrealized_pnl: Unrealized P&L from portfolio() (None if
            unavailable).
        right: Option type -- "C" for call, "P" for put.
        strike: Option strike price.
        rolling_reason: Why this position was flagged (e.g.,
            "approaching_expiry", "itm_risk").
    """

    symbol: str
    con_id: int
    current_expiry: str
    days_to_expiry: int
    position_size: float
    avg_cost: float
    current_value: float | None = None
    unrealized_pnl: float | None = None
    right: str
    strike: float
    rolling_reason: str


class RollingDecision(BaseModel):
    """Decision on how to handle an expiring option position.

    Each decision specifies one of three actions:
    - **roll**: Close current position and open a new one at target expiry.
    - **close**: Close position and take the loss (loss exceeds threshold).
    - **hold**: Let position continue (profitable, DTE > 1).

    Attributes:
        candidate: The rolling candidate being evaluated.
        should_roll: True if the position should be rolled to a new expiry.
        action: One of "roll", "close", "hold".
        target_expiry: New expiration in YYYYMMDD format (only for roll).
        target_strike: New strike price (only if strike adjustment needed).
        reasoning: Human-readable explanation of the decision logic.
        estimated_credit_debit: Estimated net credit (positive) or debit
            (negative) for the roll, if calculable.
    """

    candidate: RollingCandidate
    should_roll: bool
    action: str = Field(description='One of "roll", "close", "hold"')
    target_expiry: str | None = None
    target_strike: float | None = None
    reasoning: str
    estimated_credit_debit: float | None = None


# ---------------------------------------------------------------------------
# ExpirationMonitor
# ---------------------------------------------------------------------------


class ExpirationMonitor:
    """Monitors option positions for approaching expiration and evaluates rolling.

    Queries IB for current positions and portfolio P&L data, identifies
    options within the DTE threshold, and applies deterministic rolling
    criteria to produce actionable decisions.

    Args:
        ib: IB-async client instance (typed as Any to avoid import
            dependency in test environments).
        config: Rolling configuration with DTE threshold, loss limits,
            and target DTE.
    """

    def __init__(self, ib: Any, config: RollingConfig) -> None:
        self._ib = ib
        self._config = config

    async def scan_expiring_positions(self) -> list[RollingCandidate]:
        """Scan IB positions for options approaching expiration.

        Queries ``ib.positions()`` for all account positions, filters to
        options (``secType == "OPT"``), computes DTE, and keeps positions
        where DTE <= configured threshold. Enriches candidates with
        unrealized P&L data from ``ib.portfolio()``.

        Returns:
            List of RollingCandidate sorted by DTE ascending (most urgent
            first). Empty list if no expiring options or on IB error.
        """
        try:
            positions = self._ib.positions()
        except Exception:
            logger.warning("failed_to_fetch_positions", exc_info=True)
            return []

        if not positions:
            logger.info("no_positions_found")
            return []

        # Build portfolio lookup for P&L enrichment
        portfolio_by_conid: dict[int, Any] = {}
        try:
            portfolio_items = self._ib.portfolio()
            for item in portfolio_items:
                portfolio_by_conid[item.contract.conId] = item
        except Exception:
            logger.warning(
                "failed_to_fetch_portfolio_for_pnl_enrichment",
                exc_info=True,
            )
            # Continue without P&L data -- candidates still valuable

        today = date.today()
        candidates: list[RollingCandidate] = []

        for pos in positions:
            contract = pos.contract

            # Filter to options only
            if getattr(contract, "secType", None) != "OPT":
                continue

            # Parse expiry date
            expiry_str = getattr(
                contract, "lastTradeDateOrContractMonth", ""
            )
            if not expiry_str:
                continue

            try:
                expiry_date = datetime.strptime(expiry_str[:8], "%Y%m%d").date()
            except (ValueError, TypeError):
                logger.warning(
                    "invalid_expiry_format",
                    con_id=getattr(contract, "conId", None),
                    expiry_str=expiry_str,
                )
                continue

            dte = (expiry_date - today).days

            # Keep only positions within threshold
            if dte > self._config.dte_threshold:
                continue

            con_id = getattr(contract, "conId", 0)

            # Enrich with portfolio P&L data
            current_value: float | None = None
            unrealized_pnl: float | None = None
            portfolio_item = portfolio_by_conid.get(con_id)
            if portfolio_item is not None:
                current_value = getattr(portfolio_item, "marketValue", None)
                unrealized_pnl = getattr(
                    portfolio_item, "unrealizedPNL", None
                )

            candidate = RollingCandidate(
                symbol=getattr(contract, "symbol", ""),
                con_id=con_id,
                current_expiry=expiry_str[:8],
                days_to_expiry=dte,
                position_size=pos.position,
                avg_cost=pos.avgCost,
                current_value=current_value,
                unrealized_pnl=unrealized_pnl,
                right=getattr(contract, "right", ""),
                strike=getattr(contract, "strike", 0.0),
                rolling_reason="approaching_expiry",
            )
            candidates.append(candidate)

        # Sort by DTE ascending (most urgent first)
        candidates.sort(key=lambda c: c.days_to_expiry)

        logger.info(
            "expiring_positions_scanned",
            total_positions=len(positions),
            option_candidates=len(candidates),
            dte_threshold=self._config.dte_threshold,
        )

        return candidates

    def evaluate_rolling(
        self, candidates: list[RollingCandidate]
    ) -> list[RollingDecision]:
        """Evaluate each candidate and decide: roll, close, or hold.

        Decision logic:
        - **Close** if unrealized loss exceeds ``max_loss_multiple * abs(avg_cost)``
          -- the trade thesis is invalidated, cut the loss.
        - **Hold** if DTE > 1 AND position is profitable (unrealized_pnl > 0
          or unknown) -- let theta decay continue.
        - **Roll** otherwise: DTE is low, position is not catastrophically
          losing. Target expiry = today + preferred_roll_dte.

        Args:
            candidates: List of RollingCandidate from scan_expiring_positions.

        Returns:
            List of RollingDecision with action, reasoning, and target
            parameters for each candidate.
        """
        decisions: list[RollingDecision] = []
        today = date.today()

        for candidate in candidates:
            # Check if loss exceeds threshold -- close, don't roll
            if (
                candidate.unrealized_pnl is not None
                and candidate.unrealized_pnl < 0
                and abs(candidate.unrealized_pnl)
                > self._config.max_loss_multiple * abs(candidate.avg_cost)
            ):
                decision = RollingDecision(
                    candidate=candidate,
                    should_roll=False,
                    action="close",
                    reasoning=(
                        f"Unrealized loss ${candidate.unrealized_pnl:.2f} "
                        f"exceeds max_loss_multiple "
                        f"({self._config.max_loss_multiple}) * avg_cost "
                        f"(${abs(candidate.avg_cost):.2f}) = "
                        f"${self._config.max_loss_multiple * abs(candidate.avg_cost):.2f}. "
                        f"Trade thesis invalidated -- closing to cut loss."
                    ),
                )
                decisions.append(decision)
                continue

            # Check if position is profitable with time remaining -- hold
            if (
                candidate.days_to_expiry > 1
                and (
                    candidate.unrealized_pnl is None
                    or candidate.unrealized_pnl > 0
                )
            ):
                decision = RollingDecision(
                    candidate=candidate,
                    should_roll=False,
                    action="hold",
                    reasoning=(
                        f"DTE={candidate.days_to_expiry} > 1 and position "
                        f"is {'profitable' if candidate.unrealized_pnl and candidate.unrealized_pnl > 0 else 'P&L unknown'}. "
                        f"Letting theta decay continue."
                    ),
                )
                decisions.append(decision)
                continue

            # Default: roll the position
            target_expiry_date = today + timedelta(
                days=self._config.preferred_roll_dte
            )
            target_expiry = target_expiry_date.strftime("%Y%m%d")

            # Strike adjustment: keep same strike by default
            target_strike = candidate.strike
            strike_note = "same strike"
            if (
                self._config.allow_strike_adjustment
                and candidate.current_value is not None
            ):
                # If current_value is available, we could detect ITM,
                # but we don't have the underlying price here. Keep same
                # strike unless we have clear signal. Future enhancement
                # can add underlying price lookup for ITM detection.
                strike_note = "same strike (strike adjustment deferred)"

            decision = RollingDecision(
                candidate=candidate,
                should_roll=True,
                action="roll",
                target_expiry=target_expiry,
                target_strike=target_strike,
                reasoning=(
                    f"DTE={candidate.days_to_expiry} <= threshold "
                    f"({self._config.dte_threshold}). "
                    f"Unrealized P&L: "
                    f"{'$' + f'{candidate.unrealized_pnl:.2f}' if candidate.unrealized_pnl is not None else 'unknown'}. "
                    f"Rolling to {target_expiry} ({self._config.preferred_roll_dte} DTE) "
                    f"at {strike_note}."
                ),
            )
            decisions.append(decision)

        logger.info(
            "rolling_evaluation_complete",
            total_candidates=len(candidates),
            roll_count=sum(1 for d in decisions if d.action == "roll"),
            close_count=sum(1 for d in decisions if d.action == "close"),
            hold_count=sum(1 for d in decisions if d.action == "hold"),
        )

        return decisions

    def build_roll_proposals(
        self, decisions: list[RollingDecision]
    ) -> list[dict]:
        """Build serializable proposal dicts for close+open legs.

        For each decision with action "roll" or "close", generates:
        - A close proposal (opposite direction to unwind the position).
        - An open proposal (same direction to re-establish, only for "roll").

        These dicts are serializable for storage in PipelineState
        ``rolling_candidates`` / ``rolling_decisions``.

        Args:
            decisions: List of RollingDecision from evaluate_rolling.

        Returns:
            List of proposal dicts with keys: symbol, right, strike,
            expiry, action, quantity, strategy_type, reasoning.
        """
        proposals: list[dict] = []

        for decision in decisions:
            if decision.action not in ("roll", "close"):
                continue

            candidate = decision.candidate

            # Determine close direction: BUY to close short, SELL to close long
            close_action = "BUY" if candidate.position_size < 0 else "SELL"
            # Original direction for re-opening
            open_action = "SELL" if candidate.position_size < 0 else "BUY"

            # Close proposal
            close_proposal = {
                "symbol": candidate.symbol,
                "right": candidate.right,
                "strike": candidate.strike,
                "expiry": candidate.current_expiry,
                "action": close_action,
                "quantity": abs(candidate.position_size),
                "strategy_type": "roll_close",
                "reasoning": decision.reasoning,
                "con_id": candidate.con_id,
            }
            proposals.append(close_proposal)

            # Open proposal (only for actual rolls, not pure closes)
            if decision.action == "roll":
                open_proposal = {
                    "symbol": candidate.symbol,
                    "right": candidate.right,
                    "strike": (
                        decision.target_strike
                        if decision.target_strike is not None
                        else candidate.strike
                    ),
                    "expiry": decision.target_expiry,
                    "action": open_action,
                    "quantity": abs(candidate.position_size),
                    "strategy_type": "roll_open",
                    "reasoning": decision.reasoning,
                }
                proposals.append(open_proposal)

        logger.info(
            "roll_proposals_built",
            total_proposals=len(proposals),
            close_legs=sum(
                1 for p in proposals if p["strategy_type"] == "roll_close"
            ),
            open_legs=sum(
                1 for p in proposals if p["strategy_type"] == "roll_open"
            ),
        )

        return proposals
