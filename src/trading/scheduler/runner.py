"""Periodic pipeline runner gated by NYSE market hours.

The scheduler is a single asyncio task that loops:
  1. Sleep until either the next interval tick or the next market open.
  2. If the market is open, invoke ``app.run_agent_pipeline()``.
  3. Repeat.

Concurrency is enforced with a lock — pipeline runs never overlap, even
if a previous run takes longer than the interval. If the previous run
is still in flight the next tick is skipped (logged at warning level).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable

import structlog

from trading.scheduler.market_hours import is_market_open, next_market_open

if TYPE_CHECKING:
    from trading.app import TradingApp


PipelineCallable = Callable[[list[str], float], Awaitable[dict | None]]


class MarketScheduler:
    """Run a pipeline callable on a fixed interval during NYSE hours.

    Args:
        app: TradingApp instance. We hold a reference so we can read the
            account value at run-time and call ``run_agent_pipeline``.
        interval_seconds: Time between pipeline invocations. Default 15min.
        watchlist: Symbols to scan on each invocation. Defaults to the
            configured market_data watchlist.
        account_value: Current account NAV used for position sizing. The
            scheduler reads this dynamically (so risk sizing tracks
            growth/drawdown) — for v1 we read the configured starting
            value; once we wire the account NAV from IB we can replace.
    """

    def __init__(
        self,
        app: "TradingApp",
        *,
        interval_seconds: int = 900,
        account_value: float = 250.0,
    ) -> None:
        self._app = app
        self._interval = interval_seconds
        self._account_value = account_value
        self._watchlist: list[str] = list(app.settings.market_data.watchlist)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._run_lock = asyncio.Lock()
        self._log = structlog.get_logger("trading.scheduler")
        self._last_run_at: datetime | None = None
        self._run_count: int = 0

    async def start(self) -> None:
        """Spawn the background loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="market-scheduler")
        self._log.info(
            "scheduler.started",
            interval_seconds=self._interval,
            watchlist=self._watchlist,
        )

    async def stop(self) -> None:
        """Signal the loop to exit and wait for it to finish."""
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._log.info("scheduler.stopped", run_count=self._run_count)

    async def trigger_now(self) -> dict | None:
        """Run the pipeline once on demand. Skipped if a run is in flight."""
        if self._run_lock.locked():
            self._log.warning("scheduler.trigger_skipped_busy")
            return None
        return await self._run_once(reason="manual")

    @property
    def status(self) -> dict:
        """Snapshot for the dashboard."""
        return {
            "running": self._task is not None and not self._task.done(),
            "interval_seconds": self._interval,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "run_count": self._run_count,
            "market_open": is_market_open(),
            "next_market_open": next_market_open().astimezone(
                timezone.utc
            ).isoformat(),
        }

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if is_market_open():
                    await self._run_once(reason="scheduled")
                    await self._wait(self._interval)
                else:
                    # Sleep until the market opens, but wake at most every hour
                    # so we pick up date rollovers and stop signals reasonably.
                    delta = (
                        next_market_open() - datetime.now(timezone.utc)
                    ).total_seconds()
                    sleep_for = max(60.0, min(delta, 3600.0))
                    self._log.info(
                        "scheduler.market_closed",
                        sleep_seconds=int(sleep_for),
                    )
                    await self._wait(sleep_for)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never crash the loop. Log and back off briefly.
                self._log.warning("scheduler.loop_error", exc_info=True)
                await self._wait(30)

    async def _wait(self, seconds: float) -> None:
        """Wait up to `seconds`, returning early if stop is set."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return

    async def _run_once(self, *, reason: str) -> dict | None:
        if self._run_lock.locked():
            self._log.warning("scheduler.tick_skipped_busy", reason=reason)
            return None

        async with self._run_lock:
            self._last_run_at = datetime.now(timezone.utc)
            self._run_count += 1
            self._log.info(
                "scheduler.tick_start",
                reason=reason,
                run_index=self._run_count,
                watchlist=self._watchlist,
            )
            try:
                result = await self._app.run_agent_pipeline(
                    watchlist=self._watchlist,
                    account_value=self._account_value,
                )
                self._log.info(
                    "scheduler.tick_complete",
                    reason=reason,
                    run_index=self._run_count,
                    has_result=result is not None,
                )
                return result
            except Exception:
                self._log.error(
                    "scheduler.tick_failed",
                    reason=reason,
                    run_index=self._run_count,
                    exc_info=True,
                )
                return None
