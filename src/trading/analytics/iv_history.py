"""IB historical implied volatility data fetching with rate limiting and storage.

Fetches daily IV history from IB using OPTION_IMPLIED_VOLATILITY on STK contracts,
stores data in TimescaleDB via the IVHistory ORM model, and provides retrieval
for IV rank/percentile computation.

IB rate limits: max 60 historical data requests per 10 minutes, minimum 2 seconds
between requests. Constants use conservative margins (55 per window, 2.5s spacing).
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog
from ib_async import IB, Stock
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from trading.config import Settings
from trading.db.models import IVHistory

if TYPE_CHECKING:
    pass

# IB historical data pacing limits (conservative margins)
MAX_REQUESTS_PER_WINDOW = 55  # IB allows 60 per 10 min; leave margin
WINDOW_SECONDS = 600  # 10 minutes
MIN_REQUEST_SPACING = 2.5  # IB requires 2s minimum; add margin


class IVHistoryManager:
    """Fetches, stores, and retrieves historical implied volatility data.

    Manages IB historical data requests with built-in rate limiting to
    respect IB pacing rules. Data is persisted in TimescaleDB for
    IV rank/percentile computation by IVEngine.
    """

    def __init__(
        self,
        ib: IB,
        session_factory: async_sessionmaker,
        settings: Settings,
    ) -> None:
        self.ib = ib
        self.session_factory = session_factory
        self.settings = settings
        self._request_timestamps: list[float] = []
        self._log = structlog.get_logger().bind(component="iv_history")

    async def _wait_for_rate_limit(self) -> None:
        """Enforce IB historical data pacing limits.

        Cleans expired timestamps, waits if window is full or if minimum
        spacing between requests has not elapsed. Appends current time
        to request timestamps after waiting.
        """
        now = time.monotonic()
        waited = False

        # Clean expired timestamps outside the window
        self._request_timestamps = [
            ts for ts in self._request_timestamps
            if now - ts < WINDOW_SECONDS
        ]

        # Wait if at the per-window request limit
        if len(self._request_timestamps) >= MAX_REQUESTS_PER_WINDOW:
            oldest = self._request_timestamps[0]
            wait_time = WINDOW_SECONDS - (now - oldest) + 0.1
            if wait_time > 0:
                self._log.info(
                    "iv_history.rate_limit",
                    reason="window_full",
                    requests_in_window=len(self._request_timestamps),
                    wait_seconds=round(wait_time, 1),
                )
                await asyncio.sleep(wait_time)
                waited = True
                now = time.monotonic()

        # Enforce minimum spacing between consecutive requests
        if self._request_timestamps:
            elapsed = now - self._request_timestamps[-1]
            if elapsed < MIN_REQUEST_SPACING:
                sleep_time = MIN_REQUEST_SPACING - elapsed
                if not waited:
                    self._log.debug(
                        "iv_history.rate_limit",
                        reason="min_spacing",
                        wait_seconds=round(sleep_time, 2),
                    )
                await asyncio.sleep(sleep_time)

        self._request_timestamps.append(time.monotonic())

    async def fetch_iv_history(
        self, symbol: str, duration: str = "1 Y"
    ) -> list[tuple[date, float, float, float]]:
        """Fetch historical IV data from IB for a symbol.

        Uses STK contract (never OPT) with OPTION_IMPLIED_VOLATILITY
        whatToShow parameter to get aggregate IV for the underlying.

        Args:
            symbol: Ticker symbol (e.g. "AAPL").
            duration: IB duration string (e.g. "1 Y", "6 M").

        Returns:
            List of (date, iv_close, iv_high, iv_low) tuples.
            Empty list on error or no data.
        """
        try:
            contract = Stock(symbol, "SMART", "USD")
            await self.ib.qualifyContractsAsync(contract)

            await self._wait_for_rate_limit()

            bars = await self.ib.reqHistoricalDataAsync(
                contract=contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting="1 day",
                whatToShow="OPTION_IMPLIED_VOLATILITY",
                useRTH=True,
                formatDate=1,
            )

            if not bars:
                self._log.warning("iv_history.no_data", symbol=symbol)
                return []

            result: list[tuple[date, float, float, float]] = []
            for bar in bars:
                # Handle bar.date being string or date object
                bar_date = bar.date
                if isinstance(bar_date, str):
                    bar_date = date.fromisoformat(bar_date)
                elif isinstance(bar_date, datetime):
                    bar_date = bar_date.date()

                result.append((bar_date, bar.close, bar.high, bar.low))

            self._log.info(
                "iv_history.fetched", symbol=symbol, bars=len(result)
            )
            return result

        except Exception as exc:
            self._log.warning(
                "iv_history.fetch_failed",
                symbol=symbol,
                error=str(exc),
            )
            return []

    async def store_iv_history(
        self, symbol: str, iv_data: list[tuple[date, float, float, float]]
    ) -> int:
        """Store IV history records in the database with upsert semantics.

        Uses INSERT ... ON CONFLICT DO NOTHING to handle duplicate
        symbol+date entries idempotently.

        Args:
            symbol: Ticker symbol.
            iv_data: List of (date, iv_close, iv_high, iv_low) tuples.

        Returns:
            Number of records in the batch (not necessarily inserted if
            duplicates existed).
        """
        if not iv_data:
            return 0

        records = [
            {
                "timestamp": d,
                "symbol": symbol,
                "iv_close": iv_close,
                "iv_high": iv_high,
                "iv_low": iv_low,
            }
            for d, iv_close, iv_high, iv_low in iv_data
        ]

        async with self.session_factory() as session:
            stmt = pg_insert(IVHistory).values(records).on_conflict_do_nothing()
            await session.execute(stmt)
            await session.commit()

        count = len(records)
        self._log.info("iv_history.stored", symbol=symbol, count=count)
        return count

    async def bootstrap_symbol(self, symbol: str) -> int:
        """Fetch and store 1 year of IV history for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Number of data points stored.
        """
        iv_data = await self.fetch_iv_history(symbol, "1 Y")
        count = await self.store_iv_history(symbol, iv_data)
        self._log.info(
            "iv_history.bootstrapped", symbol=symbol, data_points=count
        )
        return count

    async def bootstrap_watchlist(self, symbols: list[str]) -> dict[str, int]:
        """Bootstrap IV history for a list of symbols sequentially.

        Processes symbols one at a time to respect IB rate limits.
        Do NOT use asyncio.gather -- historical data requests must be paced.

        Args:
            symbols: List of ticker symbols.

        Returns:
            Dict mapping symbol to number of data points stored.
        """
        results: dict[str, int] = {}
        for symbol in symbols:
            count = await self.bootstrap_symbol(symbol)
            results[symbol] = count

        total_points = sum(results.values())
        self._log.info(
            "iv_history.watchlist_bootstrapped",
            total_symbols=len(symbols),
            total_data_points=total_points,
        )
        return results

    async def get_stored_history(
        self, symbol: str, days: int = 252
    ) -> list[float]:
        """Retrieve stored IV close values for a symbol.

        Args:
            symbol: Ticker symbol.
            days: Number of historical days to retrieve (default 252 = 1 trading year).

        Returns:
            List of iv_close float values ordered by timestamp ascending.
            Empty list if no data.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

        async with self.session_factory() as session:
            stmt = (
                select(IVHistory.iv_close)
                .where(
                    IVHistory.symbol == symbol,
                    IVHistory.timestamp >= cutoff,
                )
                .order_by(IVHistory.timestamp.asc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [float(iv) for iv in rows]

    async def snapshot_current_iv(
        self, symbol: str, current_iv: float, hv: float | None = None
    ) -> None:
        """Store today's IV reading idempotently.

        Uses ON CONFLICT DO NOTHING so repeated calls for the same
        symbol+date are safe.

        Args:
            symbol: Ticker symbol.
            current_iv: Current implied volatility value.
            hv: Optional historical volatility value.
        """
        today = date.today()
        record = {
            "timestamp": today,
            "symbol": symbol,
            "iv_close": current_iv,
            "hv_close": hv,
        }

        async with self.session_factory() as session:
            stmt = pg_insert(IVHistory).values([record]).on_conflict_do_nothing()
            await session.execute(stmt)
            await session.commit()

        self._log.info("iv_history.snapshot_stored", symbol=symbol)
