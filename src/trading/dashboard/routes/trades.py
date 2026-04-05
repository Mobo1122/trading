"""Trade history REST endpoints for the dashboard API.

Provides paginated trade history with full agent reasoning chains.
Each trade is joined with the ``agent_decision_log`` table via
``Order.proposal_id == AgentDecisionLog.run_id`` to reconstruct
the complete pipeline reasoning for why the trade was made.

Routes:
    GET /api/trades/history       -- Paginated trade history with reasoning.
    GET /api/trades/{order_id}    -- Single trade detail with reasoning chain.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading.dashboard.models import ReasoningStep, TradeHistoryItem
from trading.dashboard.deps import get_db_session
from trading.db.models import AgentDecisionLog, Order

logger = structlog.get_logger().bind(component="dashboard_routes_trades")

router = APIRouter(prefix="/api/trades", tags=["trades"])


async def _build_reasoning_chain(
    session: AsyncSession, proposal_id: str
) -> list[ReasoningStep]:
    """Query AgentDecisionLog for all stages of a pipeline run.

    Joins Order.proposal_id to AgentDecisionLog.run_id to reconstruct
    the full reasoning chain (scanner -> strategist -> risk -> executor).

    Args:
        session: Active async database session.
        proposal_id: The proposal_id from the Order (equals run_id
            in AgentDecisionLog).

    Returns:
        Ordered list of ReasoningStep objects, one per pipeline stage.
    """
    if not proposal_id:
        return []

    stmt = (
        select(AgentDecisionLog)
        .where(AgentDecisionLog.run_id == proposal_id)
        .order_by(AgentDecisionLog.stage_order.asc())
    )
    result = await session.execute(stmt)
    logs = result.scalars().all()

    return [
        ReasoningStep(
            agent=log.agent_name,
            reasoning=log.reasoning,
            output_summary=log.output_summary,
            duration_ms=log.duration_ms,
        )
        for log in logs
    ]


@router.get("/history")
async def get_trade_history(
    request: Request,
    limit: int = Query(default=50, le=200, ge=1),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return paginated trade history with agent reasoning chains.

    Queries filled orders and joins each with its pipeline reasoning
    chain via proposal_id -> run_id. Returns trades ordered by most
    recent first.

    Returns:
        ``{"trades": list[TradeHistoryItem], "total": int}``
    """
    # Count total filled orders for pagination
    count_stmt = (
        select(func.count())
        .select_from(Order)
        .where(Order.current_state == "FILLED")
    )
    count_result = await session.execute(count_stmt)
    total = count_result.scalar() or 0

    # Fetch page of filled orders
    orders_stmt = (
        select(Order)
        .where(Order.current_state == "FILLED")
        .order_by(Order.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    orders_result = await session.execute(orders_stmt)
    orders = orders_result.scalars().all()

    # Build response with reasoning chains
    trades: list[TradeHistoryItem] = []
    for order in orders:
        chain = await _build_reasoning_chain(session, order.proposal_id)
        trades.append(
            TradeHistoryItem(
                order_id=order.id,
                symbol=order.symbol,
                action=order.action,
                quantity=order.quantity,
                fill_price=order.fill_price,
                commission=order.total_commission,
                created_at=order.created_at.isoformat(),
                updated_at=order.updated_at.isoformat(),
                reasoning_chain=chain if chain else None,
            )
        )

    logger.debug(
        "trades.history",
        total=total,
        returned=len(trades),
        limit=limit,
        offset=offset,
    )

    return {"trades": trades, "total": total}


@router.get("/{order_id}", response_model=TradeHistoryItem)
async def get_trade_detail(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> TradeHistoryItem:
    """Return a single trade with its full reasoning chain.

    Raises:
        HTTPException(404): If order_id does not exist.
    """
    stmt = select(Order).where(Order.id == order_id)
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    chain = await _build_reasoning_chain(session, order.proposal_id)

    return TradeHistoryItem(
        order_id=order.id,
        symbol=order.symbol,
        action=order.action,
        quantity=order.quantity,
        fill_price=order.fill_price,
        commission=order.total_commission,
        created_at=order.created_at.isoformat(),
        updated_at=order.updated_at.isoformat(),
        reasoning_chain=chain if chain else None,
    )
