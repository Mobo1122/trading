"""Unit tests for HealthMonitor.

Tests health checking logic for IB, database, and Redis components
WITHOUT requiring running services. All external dependencies are mocked.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from trading.core.health import ComponentHealth, HealthMonitor, HealthStatus


@pytest.fixture
def mock_connection_manager():
    """Create a mock IBConnectionManager."""
    mgr = MagicMock()
    type(mgr).is_connected = PropertyMock(return_value=True)
    type(mgr).reconnect_count = PropertyMock(return_value=0)
    return mgr


@pytest.fixture
def mock_db_engine():
    """Create a mock async database engine.

    The engine's connect() returns an async context manager
    whose execute() is an AsyncMock (for SELECT 1).
    """
    engine = MagicMock()
    conn = AsyncMock()
    conn.execute = AsyncMock()

    # Make connect() return an async context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=ctx)

    return engine


@pytest.fixture
def mock_redis():
    """Create a mock async Redis client."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_settings():
    """Create mock settings with trading mode."""
    settings = MagicMock()
    settings.trading.mode = "paper"
    return settings


@pytest.fixture
def health_monitor(mock_connection_manager, mock_db_engine, mock_redis, mock_settings):
    """Create a HealthMonitor with all mocked dependencies."""
    return HealthMonitor(
        connection_manager=mock_connection_manager,
        db_engine=mock_db_engine,
        redis_client=mock_redis,
        settings=mock_settings,
    )


class TestHealthCheckAllHealthy:
    """Tests when all components are healthy."""

    async def test_all_healthy(self, health_monitor):
        """When IB, DB, and Redis are all up, overall is HEALTHY."""
        status = await health_monitor.check_health()

        assert status.ib_connected is True
        assert status.db_connected is True
        assert status.redis_connected is True
        assert status.overall == ComponentHealth.HEALTHY


class TestHealthCheckDegraded:
    """Tests for degraded health state."""

    async def test_ib_disconnected_is_degraded(
        self, mock_connection_manager, mock_db_engine, mock_redis, mock_settings
    ):
        """IB disconnected with DB and Redis up results in DEGRADED."""
        type(mock_connection_manager).is_connected = PropertyMock(return_value=False)
        type(mock_connection_manager).reconnect_count = PropertyMock(return_value=3)

        monitor = HealthMonitor(
            mock_connection_manager, mock_db_engine, mock_redis, mock_settings
        )
        status = await monitor.check_health()

        assert status.ib_connected is False
        assert status.ib_reconnect_count == 3
        assert status.overall == ComponentHealth.DEGRADED


class TestHealthCheckUnhealthy:
    """Tests for unhealthy health state."""

    async def test_db_down_is_unhealthy(
        self, mock_connection_manager, mock_db_engine, mock_redis, mock_settings
    ):
        """Database failure results in UNHEALTHY regardless of other components."""
        # Make DB check fail
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_db_engine.connect = MagicMock(return_value=ctx)

        monitor = HealthMonitor(
            mock_connection_manager, mock_db_engine, mock_redis, mock_settings
        )
        status = await monitor.check_health()

        assert status.db_connected is False
        assert status.overall == ComponentHealth.UNHEALTHY

    async def test_redis_down_is_unhealthy(
        self, mock_connection_manager, mock_db_engine, mock_redis, mock_settings
    ):
        """Redis failure results in UNHEALTHY regardless of other components."""
        mock_redis.ping = AsyncMock(side_effect=Exception("connection refused"))

        monitor = HealthMonitor(
            mock_connection_manager, mock_db_engine, mock_redis, mock_settings
        )
        status = await monitor.check_health()

        assert status.redis_connected is False
        assert status.overall == ComponentHealth.UNHEALTHY


class TestHealthCheckMetadata:
    """Tests for health status metadata fields."""

    async def test_uptime_increases(self, health_monitor):
        """Uptime should be greater than zero after creation."""
        status = await health_monitor.check_health()
        assert status.uptime_seconds > 0

    async def test_health_status_includes_trading_mode(self, health_monitor):
        """Health status includes the current trading mode."""
        status = await health_monitor.check_health()
        assert status.trading_mode == "paper"

    async def test_last_check_is_set(self, health_monitor):
        """Health status includes a last_check timestamp."""
        status = await health_monitor.check_health()
        assert status.last_check is not None


class TestComputeOverall:
    """Tests for the _compute_overall static method."""

    def test_all_true_is_healthy(self):
        """All components up returns HEALTHY."""
        assert HealthMonitor._compute_overall(True, True, True) == ComponentHealth.HEALTHY

    def test_ib_false_is_degraded(self):
        """IB down with DB and Redis up returns DEGRADED."""
        assert HealthMonitor._compute_overall(False, True, True) == ComponentHealth.DEGRADED

    def test_db_false_is_unhealthy(self):
        """DB down returns UNHEALTHY."""
        assert HealthMonitor._compute_overall(True, False, True) == ComponentHealth.UNHEALTHY

    def test_redis_false_is_unhealthy(self):
        """Redis down returns UNHEALTHY."""
        assert HealthMonitor._compute_overall(True, True, False) == ComponentHealth.UNHEALTHY

    def test_all_false_is_unhealthy(self):
        """All components down returns UNHEALTHY."""
        assert HealthMonitor._compute_overall(False, False, False) == ComponentHealth.UNHEALTHY
