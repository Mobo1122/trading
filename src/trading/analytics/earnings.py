"""Earnings calendar integration with Finnhub API.

Fetches upcoming earnings dates, stores them in the database, and exposes
earnings flags for underlyings approaching earnings events. Options premiums
expand before earnings (IV expansion) and collapse after (IV crush). The
scanner agent uses earnings flags to filter and prioritize opportunities.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from trading.config import Settings
from trading.db.models import EarningsEvent
from trading.market_data.models import EarningsFlag


class EarningsCalendar:
    """Service for fetching, storing, and querying earnings events.

    Integrates with the Finnhub API to fetch upcoming earnings dates.
    Supports both the finnhub-python SDK and a direct httpx fallback.
    Results are cached in-memory for 24 hours and persisted to the
    earnings_events database table with upsert semantics.

    Args:
        session_factory: SQLAlchemy async session factory for DB operations.
        settings: Application settings containing API key and lookout config.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._cache: dict[str, list[EarningsFlag]] = {}
        self._last_refresh: float | None = None
        self._log = structlog.get_logger().bind(component="earnings_calendar")

    async def fetch_earnings(
        self, symbol: str, from_date: date, to_date: date
    ) -> list[dict]:
        """Fetch earnings calendar data for a symbol from Finnhub.

        Tries the finnhub-python SDK first (run in executor since it is
        synchronous). Falls back to httpx for direct REST API calls.

        Args:
            symbol: Ticker symbol (e.g. "AAPL").
            from_date: Start of the date range.
            to_date: End of the date range.

        Returns:
            List of raw earnings dicts from Finnhub, or empty list on error.
        """
        api_key = self._settings.market_data.finnhub_api_key
        if not api_key:
            self._log.warning("earnings.no_api_key", symbol=symbol)
            return []

        # Try finnhub SDK first
        try:
            import finnhub  # noqa: F811

            client = finnhub.Client(api_key=api_key)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: client.earnings_calendar(
                    _from=from_date.isoformat(),
                    to=to_date.isoformat(),
                    symbol=symbol,
                ),
            )
            return result.get("earningsCalendar", [])
        except ImportError:
            pass  # Fall through to httpx
        except Exception as exc:
            self._log.warning(
                "earnings.fetch_failed",
                symbol=symbol,
                error=str(exc),
                method="finnhub_sdk",
            )
            # Fall through to httpx as fallback

        # httpx fallback
        try:
            import httpx

            async with httpx.AsyncClient() as http:
                resp = await http.get(
                    "https://finnhub.io/api/v1/calendar/earnings",
                    params={
                        "from": from_date.isoformat(),
                        "to": to_date.isoformat(),
                        "symbol": symbol,
                        "token": api_key,
                    },
                    timeout=10.0,
                )
                resp.raise_for_status()
                result = resp.json()
                return result.get("earningsCalendar", [])
        except Exception as exc:
            self._log.warning(
                "earnings.fetch_failed",
                symbol=symbol,
                error=str(exc),
                method="httpx",
            )
            return []

    async def store_earnings(self, earnings_data: list[dict]) -> int:
        """Persist earnings data to the database with upsert semantics.

        Uses PostgreSQL ON CONFLICT DO UPDATE to refresh eps_estimate,
        revenue_estimate, and hour if the earnings entry already exists.

        Args:
            earnings_data: List of raw earnings dicts from Finnhub.

        Returns:
            Number of earnings entries upserted.
        """
        if not earnings_data:
            return 0

        count = 0
        async with self._session_factory() as session:
            for entry in earnings_data:
                try:
                    earnings_date = date.fromisoformat(entry["date"])
                    symbol = entry["symbol"]
                    hour = entry.get("hour")
                    eps_estimate = entry.get("epsEstimate")
                    revenue_estimate = entry.get("revenueEstimate")

                    stmt = (
                        pg_insert(EarningsEvent)
                        .values(
                            symbol=symbol,
                            earnings_date=earnings_date,
                            hour=hour,
                            eps_estimate=eps_estimate,
                            revenue_estimate=revenue_estimate,
                        )
                        .on_conflict_do_update(
                            index_elements=["symbol", "earnings_date"],
                            set_={
                                "hour": hour,
                                "eps_estimate": eps_estimate,
                                "revenue_estimate": revenue_estimate,
                                "fetched_at": func.now(),
                            },
                        )
                    )
                    await session.execute(stmt)
                    count += 1
                except (KeyError, ValueError) as exc:
                    self._log.warning(
                        "earnings.parse_failed",
                        entry=str(entry),
                        error=str(exc),
                    )
            await session.commit()

        self._log.info("earnings.stored", count=count)
        return count

    async def refresh_watchlist(
        self, symbols: list[str]
    ) -> dict[str, int]:
        """Refresh earnings data for a list of watchlist symbols.

        Fetches from Finnhub and stores for each symbol sequentially.
        Clears the in-memory cache to force re-computation of flags.

        Args:
            symbols: List of ticker symbols to refresh.

        Returns:
            Dict mapping symbol to number of earnings entries stored.
        """
        from_date = date.today()
        lookout_days = self._settings.market_data.earnings_lookout_days
        to_date = from_date + timedelta(days=lookout_days * 4)

        results: dict[str, int] = {}
        total_events = 0
        for symbol in symbols:
            data = await self.fetch_earnings(symbol, from_date, to_date)
            count = await self.store_earnings(data)
            results[symbol] = count
            total_events += count

        self._last_refresh = time.time()
        self._cache.clear()

        self._log.info(
            "earnings.watchlist_refreshed",
            total_symbols=len(symbols),
            total_events=total_events,
        )
        return results

    async def get_earnings_flags(
        self, symbols: list[str]
    ) -> list[EarningsFlag]:
        """Get earnings flags for symbols within the lookout window.

        Checks in-memory cache first. On cache miss, queries the database
        for earnings_events within the configured lookout window.

        Args:
            symbols: List of ticker symbols to check.

        Returns:
            List of EarningsFlag models sorted by earnings_date ascending.
        """
        # Check if all symbols are cached
        if self._cache and all(s in self._cache for s in symbols):
            flags: list[EarningsFlag] = []
            for s in symbols:
                flags.extend(self._cache[s])
            flags.sort(key=lambda f: f.earnings_date)
            return flags

        lookout_days = self._settings.market_data.earnings_lookout_days
        today = date.today()
        cutoff = today + timedelta(days=lookout_days)

        async with self._session_factory() as session:
            stmt = (
                select(EarningsEvent)
                .where(
                    EarningsEvent.symbol.in_(symbols),
                    EarningsEvent.earnings_date >= today,
                    EarningsEvent.earnings_date <= cutoff,
                )
                .order_by(EarningsEvent.earnings_date.asc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        # Build flags and update cache
        flags = []
        cache_update: dict[str, list[EarningsFlag]] = {s: [] for s in symbols}
        for row in rows:
            days_until = (row.earnings_date - today).days
            flag = EarningsFlag(
                symbol=row.symbol,
                earnings_date=row.earnings_date,
                days_until=days_until,
                hour=row.hour,
                eps_estimate=row.eps_estimate,
                revenue_estimate=row.revenue_estimate,
                fetched_at=row.fetched_at,
            )
            flags.append(flag)
            if row.symbol in cache_update:
                cache_update[row.symbol].append(flag)

        self._cache.update(cache_update)
        return flags

    async def get_earnings_flag(self, symbol: str) -> EarningsFlag | None:
        """Get the next upcoming earnings flag for a single symbol.

        Convenience method wrapping get_earnings_flags for a single symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            The nearest upcoming EarningsFlag, or None if no earnings in window.
        """
        flags = await self.get_earnings_flags([symbol])
        for flag in flags:
            if flag.symbol == symbol:
                return flag
        return None

    def needs_refresh(self) -> bool:
        """Check whether a daily earnings refresh is due.

        Returns True if no refresh has occurred or the last refresh
        was more than 24 hours ago.
        """
        return (
            self._last_refresh is None
            or time.time() - self._last_refresh > 86400
        )
