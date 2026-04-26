"""Tests for the MarketScheduler runner.

We don't test the full asyncio loop; we test the discrete pieces:
  - trigger_now invokes app.run_agent_pipeline with the right args
  - concurrent triggers don't overlap
  - status() returns the right shape
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from trading.scheduler.runner import MarketScheduler


def _fake_app(watchlist: list[str] | None = None):
    """Build a minimal stand-in for TradingApp."""
    settings = SimpleNamespace(
        market_data=SimpleNamespace(
            watchlist=watchlist or ["SPY", "QQQ"],
        ),
    )
    app = SimpleNamespace(
        settings=settings,
        run_agent_pipeline=AsyncMock(return_value={"ok": True}),
    )
    return app


@pytest.mark.asyncio
async def test_trigger_now_invokes_pipeline_with_settings_watchlist() -> None:
    app = _fake_app(watchlist=["AAPL", "MSFT"])
    scheduler = MarketScheduler(app, account_value=300.0)

    result = await scheduler.trigger_now()

    assert result == {"ok": True}
    app.run_agent_pipeline.assert_awaited_once_with(
        watchlist=["AAPL", "MSFT"],
        account_value=300.0,
    )
    assert scheduler._run_count == 1
    assert scheduler._last_run_at is not None


@pytest.mark.asyncio
async def test_concurrent_triggers_dont_overlap() -> None:
    app = _fake_app()

    pipeline_started = asyncio.Event()
    allow_finish = asyncio.Event()

    async def slow_pipeline(*, watchlist, account_value):  # noqa: ARG001
        pipeline_started.set()
        await allow_finish.wait()
        return {"ok": True}

    app.run_agent_pipeline = slow_pipeline

    scheduler = MarketScheduler(app)

    # Start the first trigger (will block on allow_finish event)
    first = asyncio.create_task(scheduler.trigger_now())
    await pipeline_started.wait()

    # Second trigger while first is still running — must skip immediately.
    second = await scheduler.trigger_now()
    assert second is None
    assert scheduler._run_count == 1, "lock should prevent double-run"

    allow_finish.set()
    await first


@pytest.mark.asyncio
async def test_status_shape() -> None:
    app = _fake_app()
    scheduler = MarketScheduler(app, interval_seconds=300)

    snap = scheduler.status

    assert set(snap.keys()) == {
        "running",
        "interval_seconds",
        "last_run_at",
        "run_count",
        "market_open",
        "next_market_open",
    }
    assert snap["running"] is False
    assert snap["interval_seconds"] == 300
    assert snap["last_run_at"] is None
    assert snap["run_count"] == 0
    # next_market_open is always an ISO timestamp string
    assert isinstance(snap["next_market_open"], str)
    assert snap["next_market_open"].endswith("+00:00")
