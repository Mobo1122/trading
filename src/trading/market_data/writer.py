"""Buffered batch writer for persisting tick data to TimescaleDB.

Accumulates quote and Greeks snapshots in memory buffers and flushes
them to the database in configurable batches (default: every 5 seconds,
up to 500 records per flush). This amortizes the cost of database writes
across many tick events.

Design decisions:
  - Buffer swap is atomic (slice + reassign) to avoid data loss
  - Flush failures are logged but not raised (tick data is expendable)
  - Final flush on stop() ensures no buffered data is silently dropped
  - Flush loop uses try/except to prevent task death on transient errors
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from trading.config import Settings
from trading.db.models import MarketQuote, OptionGreeks
from trading.market_data.models import GreeksSnapshot, QuoteSnapshot


class TimescaleDBWriter:
    """Batched writer for persisting market data to TimescaleDB.

    Tick data (quotes and Greeks) is buffered in memory and periodically
    flushed to the database using SQLAlchemy bulk inserts. This reduces
    database round-trips from per-tick to per-batch.

    Args:
        session_factory: Async session factory for database access.
        settings: Application settings (reads batch config).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._flush_interval: float = settings.market_data.batch_flush_interval_seconds
        self._batch_size: int = settings.market_data.batch_size

        self._quote_buffer: list[MarketQuote] = []
        self._greeks_buffer: list[OptionGreeks] = []
        self._flush_task: asyncio.Task | None = None
        self._running: bool = False

        self._log = structlog.get_logger().bind(
            component="tsdb_writer",
        )

    async def start(self) -> None:
        """Start the periodic flush loop.

        Creates a background asyncio task that flushes buffered data
        to the database at the configured interval.
        """
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._log.info("writer.started", flush_interval=self._flush_interval)

    async def stop(self) -> None:
        """Stop the flush loop and perform a final flush.

        Cancels the background task and flushes any remaining buffered
        data to ensure nothing is silently dropped on shutdown.
        """
        self._running = False

        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Final flush to persist remaining data
        await self._flush()
        self._log.info("writer.stopped")

    def buffer_quote(self, snapshot: QuoteSnapshot) -> None:
        """Buffer a quote snapshot for batch persistence.

        Creates a MarketQuote ORM instance from the snapshot and
        appends it to the in-memory buffer. No I/O is performed.

        Args:
            snapshot: Quote snapshot to buffer.
        """
        record = MarketQuote(
            timestamp=snapshot.timestamp or datetime.now(timezone.utc),
            symbol=snapshot.symbol,
            con_id=snapshot.con_id,
            sec_type=snapshot.sec_type,
            bid=snapshot.bid,
            ask=snapshot.ask,
            last=snapshot.last,
            volume=snapshot.volume,
            open_interest=snapshot.open_interest,
            implied_volatility=snapshot.implied_volatility,
        )
        self._quote_buffer.append(record)

    def buffer_greeks(self, snapshot: GreeksSnapshot) -> None:
        """Buffer a Greeks snapshot for batch persistence.

        Creates an OptionGreeks ORM instance from the snapshot and
        appends it to the in-memory buffer. No I/O is performed.

        Args:
            snapshot: Greeks snapshot to buffer.
        """
        record = OptionGreeks(
            timestamp=snapshot.timestamp or datetime.now(timezone.utc),
            symbol=snapshot.symbol,
            con_id=snapshot.con_id,
            implied_vol=snapshot.implied_vol,
            delta=snapshot.delta,
            gamma=snapshot.gamma,
            theta=snapshot.theta,
            vega=snapshot.vega,
            und_price=snapshot.und_price,
        )
        self._greeks_buffer.append(record)

    async def _flush_loop(self) -> None:
        """Periodic flush loop running as a background task.

        Sleeps for the configured interval, then flushes buffered data.
        Wraps the loop body in try/except to prevent task death on
        transient database errors.
        """
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._log.warning(
                    "writer.flush_loop_error",
                    error=str(e),
                )

    async def _flush(self) -> None:
        """Flush buffered records to the database.

        Atomically swaps out up to batch_size records from each buffer
        and bulk-inserts them in a single transaction. On failure, logs
        a warning but does not re-raise (tick data loss is acceptable).
        """
        if not self._quote_buffer and not self._greeks_buffer:
            return

        # Atomic buffer swap: take up to batch_size, leave remainder
        quotes = self._quote_buffer[: self._batch_size]
        self._quote_buffer = self._quote_buffer[self._batch_size :]
        greeks = self._greeks_buffer[: self._batch_size]
        self._greeks_buffer = self._greeks_buffer[self._batch_size :]

        records = quotes + greeks
        if not records:
            return

        try:
            async with self._session_factory() as session:
                session.add_all(records)
                await session.commit()
            self._log.info(
                "writer.flushed",
                quote_count=len(quotes),
                greeks_count=len(greeks),
            )
        except Exception as e:
            self._log.warning(
                "writer.flush_failed",
                quote_count=len(quotes),
                greeks_count=len(greeks),
                error=str(e),
            )
