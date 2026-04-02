"""Market data streaming and subscription management.

Provides the complete real-time market data pipeline:
- Pydantic models for quotes, Greeks, IV analytics, and earnings
- Subscription lifecycle management with IB line limits
- Redis pub/sub distribution and latest-value caching
- Buffered TimescaleDB persistence
- Staleness detection for data quality monitoring
"""

from trading.market_data.distributor import RedisDistributor
from trading.market_data.manager import MarketDataManager
from trading.market_data.models import (
    EarningsFlag,
    GreeksSnapshot,
    IVData,
    QuoteSnapshot,
    SubscriptionInfo,
    SubscriptionPriority,
)
from trading.market_data.staleness import StalenessMonitor
from trading.market_data.subscriber import SubscriptionManager
from trading.market_data.writer import TimescaleDBWriter

__all__ = [
    "QuoteSnapshot",
    "GreeksSnapshot",
    "IVData",
    "EarningsFlag",
    "SubscriptionInfo",
    "SubscriptionPriority",
    "MarketDataManager",
    "SubscriptionManager",
    "RedisDistributor",
    "TimescaleDBWriter",
    "StalenessMonitor",
]
