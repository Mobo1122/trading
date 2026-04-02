"""Pydantic data models for market data streaming and analytics.

Defines the core data structures used throughout Phase 2:
- QuoteSnapshot: Real-time quote data from IB streaming
- GreeksSnapshot: Option Greeks from IB model calculations
- IVData: Implied volatility analytics (rank, percentile, history)
- EarningsFlag: Upcoming earnings event metadata
- SubscriptionInfo/Priority: Market data subscription management

All float fields from IB are NaN-safe via _safe_float helper.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


def _safe_float(value: float | None) -> float | None:
    """Convert NaN to None for JSON-safe serialization.

    IB API frequently returns NaN for unavailable numeric fields.
    This helper normalizes them to None for consistent downstream handling.
    """
    if value is None:
        return None
    try:
        if math.isnan(value):
            return None
    except TypeError:
        return None
    return float(value)


class SubscriptionPriority(str, Enum):
    """Priority levels for market data subscriptions.

    Determines eviction order when subscription limit is reached:
    - HIGH: open positions, never evicted
    - MEDIUM: watchlist underlyings
    - LOW: agent-requested, evictable via LRU
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SubscriptionInfo(BaseModel):
    """Tracks an active market data subscription line."""

    con_id: int
    symbol: str
    sec_type: str
    priority: SubscriptionPriority
    subscribed_at: datetime
    last_update: datetime | None = None


class QuoteSnapshot(BaseModel):
    """Real-time quote data extracted from an IB Ticker.

    Captures bid/ask/last, volume, open interest, and aggregate
    implied volatility for both stocks and options.
    """

    symbol: str
    con_id: int
    sec_type: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    put_open_interest: float | None = None
    call_open_interest: float | None = None
    put_volume: float | None = None
    call_volume: float | None = None
    implied_volatility: float | None = None
    timestamp: datetime | None = None
    is_stale: bool = False

    @classmethod
    def from_ticker(cls, ticker) -> QuoteSnapshot:
        """Create a QuoteSnapshot from an ib_async Ticker object.

        All float fields are NaN-safe: IB NaN values become None.
        """
        return cls(
            symbol=ticker.contract.symbol,
            con_id=ticker.contract.conId,
            sec_type=ticker.contract.secType,
            bid=_safe_float(ticker.bid),
            ask=_safe_float(ticker.ask),
            last=_safe_float(ticker.last),
            volume=_safe_float(ticker.volume),
            open_interest=_safe_float(getattr(ticker, "openInterest", None)),
            put_open_interest=_safe_float(ticker.putOpenInterest),
            call_open_interest=_safe_float(ticker.callOpenInterest),
            put_volume=_safe_float(ticker.putVolume),
            call_volume=_safe_float(ticker.callVolume),
            implied_volatility=_safe_float(ticker.impliedVolatility),
            timestamp=ticker.time,
        )


class GreeksSnapshot(BaseModel):
    """Option Greeks from IB model calculations.

    Extracted from ticker.modelGreeks (OptionComputation object).
    Returns None from from_ticker if modelGreeks is unavailable.
    """

    symbol: str
    con_id: int
    implied_vol: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    und_price: float | None = None
    timestamp: datetime | None = None

    @classmethod
    def from_ticker(cls, ticker) -> Optional[GreeksSnapshot]:
        """Create a GreeksSnapshot from an ib_async Ticker object.

        Returns None if ticker.modelGreeks is not available.
        All float fields are NaN-safe.
        """
        if ticker.modelGreeks is None:
            return None
        greeks = ticker.modelGreeks
        return cls(
            symbol=ticker.contract.symbol,
            con_id=ticker.contract.conId,
            implied_vol=_safe_float(greeks.impliedVol),
            delta=_safe_float(greeks.delta),
            gamma=_safe_float(greeks.gamma),
            theta=_safe_float(greeks.theta),
            vega=_safe_float(greeks.vega),
            und_price=_safe_float(greeks.undPrice),
            timestamp=ticker.time,
        )


class IVData(BaseModel):
    """Implied volatility analytics for a symbol.

    Computed from historical IV data. iv_rank and iv_percentile
    require sufficient history (data_points > 0) to be meaningful.
    """

    symbol: str
    current_iv: float | None = None
    iv_rank: float | None = None
    iv_percentile: float | None = None
    iv_high_52w: float | None = None
    iv_low_52w: float | None = None
    hv_current: float | None = None
    data_points: int = 0
    computed_at: datetime | None = None


class EarningsFlag(BaseModel):
    """Upcoming earnings event metadata for a symbol.

    Used to flag symbols approaching earnings for special
    handling in position sizing and strategy selection.
    """

    symbol: str
    earnings_date: date
    days_until: int
    hour: str | None = None
    eps_estimate: float | None = None
    revenue_estimate: float | None = None
    fetched_at: datetime
