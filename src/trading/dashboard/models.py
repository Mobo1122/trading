"""Pydantic response models for the dashboard API.

Defines all request/response models used by the FastAPI dashboard server
endpoints and WebSocket messages. Models use from_attributes=True where
appropriate for ORM compatibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PositionResponse(BaseModel):
    """Current position data for a single instrument."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    sec_type: str | None = None
    quantity: int
    avg_cost: float | None = None
    current_price: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    market_value: float | None = None


class PortfolioSummary(BaseModel):
    """Aggregated portfolio-level summary metrics."""

    model_config = ConfigDict(from_attributes=True)

    total_market_value: float
    total_unrealized_pnl: float
    total_realized_pnl: float
    net_liquidation: float


class GreeksResponse(BaseModel):
    """Greeks exposure data, either per-position or aggregated portfolio.

    When is_portfolio is True, delta/gamma/theta/vega represent the sum
    across all option contracts in the portfolio.
    """

    model_config = ConfigDict(from_attributes=True)

    delta: float
    gamma: float
    theta: float
    vega: float
    symbol: str | None = None
    is_portfolio: bool = False


class ReasoningStep(BaseModel):
    """A single step in the agent reasoning chain for a trade decision."""

    agent: str
    reasoning: str | None = None
    output_summary: str | None = None
    duration_ms: int | None = None


class TradeHistoryItem(BaseModel):
    """A completed or in-progress trade with its reasoning chain."""

    model_config = ConfigDict(from_attributes=True)

    order_id: str
    symbol: str
    action: str
    quantity: float
    fill_price: float | None = None
    commission: float | None = None
    created_at: str
    updated_at: str
    reasoning_chain: list[ReasoningStep] | None = None


class HealthStatus(BaseModel):
    """System health status for all critical components.

    data_freshness maps symbol to seconds since last market data update.
    agent_last_seen maps agent name to ISO timestamp of last AgentDecisionLog entry.
    """

    ib_connected: bool
    db_connected: bool
    redis_connected: bool
    data_freshness: dict[str, float]
    last_heartbeat: str | None = None
    pipeline_status: str = "idle"
    agent_last_seen: dict[str, str] = {}


class ScenarioRequest(BaseModel):
    """Request parameters for what-if scenario analysis."""

    underlying_change_pct: float
    iv_change_pct: float
    days_forward: int
    risk_free_rate: float = 0.05


class ScenarioResponse(BaseModel):
    """Result of a what-if scenario analysis."""

    current_value: float
    scenario_value: float
    pnl: float
    pnl_percent: float
    per_position: list[dict] = []


class WSMessage(BaseModel):
    """WebSocket message envelope for all WS communication."""

    type: str
    channel: str | None = None
    data: Any = None
