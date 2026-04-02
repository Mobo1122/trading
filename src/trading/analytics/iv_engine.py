"""IV rank and percentile computation engine with caching.

Computes IV rank and IV percentile from stored historical IV data:
- IV Rank: Where current IV sits in the 52-week range (0-100)
- IV Percentile: Percentage of days with IV below current (0-100)

Both metrics return None when insufficient history exists (cold start),
never misleading numeric defaults like 0 or 50.

Results are cached per-symbol with a configurable refresh interval
(default 15 minutes from settings).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import structlog

from trading.analytics.iv_history import IVHistoryManager
from trading.config import Settings
from trading.market_data.models import IVData


class IVEngine:
    """Computes IV rank and percentile from stored history with caching.

    Static methods provide pure computation suitable for unit testing.
    Instance methods add caching and database integration via IVHistoryManager.
    """

    def __init__(self, iv_history: IVHistoryManager, settings: Settings) -> None:
        self.iv_history = iv_history
        self._cache: dict[str, IVData] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._refresh_interval: float = (
            settings.market_data.iv_refresh_interval_minutes * 60
        )
        self._log = structlog.get_logger().bind(component="iv_engine")

    @staticmethod
    def calculate_iv_rank(
        current_iv: float, iv_history: list[float]
    ) -> float | None:
        """Calculate IV rank: position of current IV in the historical range.

        IV Rank = (Current IV - 52w Low) / (52w High - 52w Low) * 100

        Args:
            current_iv: Current implied volatility.
            iv_history: List of historical IV close values.

        Returns:
            IV rank as a float 0-100, or None if insufficient data (<20 points).
        """
        if not iv_history or len(iv_history) < 20:
            return None

        low = min(iv_history)
        high = max(iv_history)

        if high == low:
            return 50.0

        result = ((current_iv - low) / (high - low)) * 100.0
        return max(0.0, min(100.0, result))

    @staticmethod
    def calculate_iv_percentile(
        current_iv: float, iv_history: list[float]
    ) -> float | None:
        """Calculate IV percentile: % of historical days with IV below current.

        IV Percentile = (Days below current IV / Total days) * 100

        Args:
            current_iv: Current implied volatility.
            iv_history: List of historical IV close values.

        Returns:
            IV percentile as a float 0-100, or None if insufficient data (<20 points).
        """
        if not iv_history or len(iv_history) < 20:
            return None

        below = sum(1 for iv in iv_history if iv < current_iv)
        return (below / len(iv_history)) * 100.0

    async def compute(
        self,
        symbol: str,
        current_iv: float | None = None,
        hv: float | None = None,
    ) -> IVData:
        """Compute IV analytics for a symbol, using cache when fresh.

        Fetches stored history from the database, computes IV rank and
        percentile, and caches the result. Returns cached values if
        within the refresh interval.

        Args:
            symbol: Ticker symbol.
            current_iv: Current IV (if None, uses most recent from history).
            hv: Current historical volatility (optional).

        Returns:
            IVData with rank, percentile, and metadata.
        """
        # Return cached value if fresh
        if symbol in self._cache:
            cache_age = time.time() - self._cache_timestamps[symbol]
            if cache_age < self._refresh_interval:
                return self._cache[symbol]

        history = await self.iv_history.get_stored_history(symbol, days=252)

        # Fall back to most recent history value if current_iv not provided
        if current_iv is None and history:
            current_iv = history[-1]

        if current_iv is not None and history:
            iv_rank = self.calculate_iv_rank(current_iv, history)
            iv_percentile = self.calculate_iv_percentile(current_iv, history)
            iv_high = max(history)
            iv_low = min(history)
        else:
            iv_rank = None
            iv_percentile = None
            iv_high = None
            iv_low = None

        iv_data = IVData(
            symbol=symbol,
            current_iv=current_iv,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            iv_high_52w=iv_high,
            iv_low_52w=iv_low,
            hv_current=hv,
            data_points=len(history),
            computed_at=datetime.now(tz=timezone.utc),
        )

        # Cache the result
        self._cache[symbol] = iv_data
        self._cache_timestamps[symbol] = time.time()

        self._log.info(
            "iv_engine.computed",
            symbol=symbol,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            data_points=len(history),
        )
        return iv_data

    async def compute_batch(
        self,
        symbols: list[str],
        current_ivs: dict[str, float] | None = None,
    ) -> dict[str, IVData]:
        """Compute IV analytics for multiple symbols concurrently.

        Uses asyncio.gather since each compute triggers independent DB reads.

        Args:
            symbols: List of ticker symbols.
            current_ivs: Optional dict mapping symbol to current IV.

        Returns:
            Dict mapping symbol to IVData.
        """
        tasks = [
            self.compute(
                s,
                current_iv=current_ivs.get(s) if current_ivs else None,
            )
            for s in symbols
        ]
        results = await asyncio.gather(*tasks)
        return {symbol: result for symbol, result in zip(symbols, results)}

    def invalidate_cache(self, symbol: str | None = None) -> None:
        """Invalidate cached IV data.

        Args:
            symbol: Symbol to invalidate, or None to clear all.
        """
        if symbol is None:
            self._cache.clear()
            self._cache_timestamps.clear()
        else:
            self._cache.pop(symbol, None)
            self._cache_timestamps.pop(symbol, None)

    def get_cached(self, symbol: str) -> IVData | None:
        """Return cached IVData for a symbol, or None if not cached.

        May return stale data -- caller should check computed_at.
        """
        return self._cache.get(symbol)
