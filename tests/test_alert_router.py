"""Unit tests for the alert routing system.

Tests AlertRouter routing logic, SlackNotifier Block Kit formatting,
and SMSNotifier cooldown enforcement. Uses AsyncMock for external
dependencies (Redis, webhook client, httpx).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading.alerts.config import AlertConfig
from trading.alerts.router import AlertRouter
from trading.alerts.slack import SlackNotifier
from trading.alerts.sms import SMSNotifier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alert_config_all_enabled() -> AlertConfig:
    """AlertConfig with both Slack and SMS enabled."""
    return AlertConfig(
        slack_enabled=True,
        slack_webhook_url="https://hooks.slack.com/test",
        sms_enabled=True,
        twilio_account_sid="AC_TEST",
        twilio_auth_token="auth_test",
        twilio_from_number="+15551234567",
        twilio_to_number="+15559876543",
        sms_channels=[
            "alerts:risk_breach",
            "alerts:circuit_breaker",
            "alerts:system_error",
        ],
        sms_cooldown_seconds=300,
    )


@pytest.fixture
def alert_config_slack_only() -> AlertConfig:
    """AlertConfig with only Slack enabled."""
    return AlertConfig(
        slack_enabled=True,
        slack_webhook_url="https://hooks.slack.com/test",
        sms_enabled=False,
    )


@pytest.fixture
def alert_config_disabled() -> AlertConfig:
    """AlertConfig with everything disabled."""
    return AlertConfig(slack_enabled=False, sms_enabled=False)


@pytest.fixture
def mock_slack() -> AsyncMock:
    """Mock SlackNotifier."""
    return AsyncMock(spec=SlackNotifier)


@pytest.fixture
def mock_sms() -> AsyncMock:
    """Mock SMSNotifier."""
    return AsyncMock(spec=SMSNotifier)


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock async Redis client."""
    return AsyncMock()


# ---------------------------------------------------------------------------
# AlertRouter._route tests
# ---------------------------------------------------------------------------


class TestAlertRouterRoute:
    """Tests for AlertRouter._route routing logic."""

    async def test_routes_to_slack_for_all_channels(
        self,
        mock_redis: AsyncMock,
        mock_slack: AsyncMock,
        mock_sms: AsyncMock,
        alert_config_all_enabled: AlertConfig,
    ) -> None:
        """Slack is called for every channel when slack_enabled."""
        router = AlertRouter(
            redis=mock_redis,
            slack_notifier=mock_slack,
            sms_notifier=mock_sms,
            config=alert_config_all_enabled,
        )
        data = {"symbol": "SPY", "strategy": "iron_condor"}

        for channel in AlertRouter.CHANNELS:
            mock_slack.reset_mock()
            await router._route(channel, data)
            mock_slack.send.assert_called_once_with(channel, data)

    async def test_routes_sms_only_for_sms_channels(
        self,
        mock_redis: AsyncMock,
        mock_slack: AsyncMock,
        mock_sms: AsyncMock,
        alert_config_all_enabled: AlertConfig,
    ) -> None:
        """SMS is called only for channels in sms_channels."""
        router = AlertRouter(
            redis=mock_redis,
            slack_notifier=mock_slack,
            sms_notifier=mock_sms,
            config=alert_config_all_enabled,
        )
        data = {"reason": "daily loss exceeded"}

        # SMS channel -- should send
        await router._route("alerts:risk_breach", data)
        mock_sms.send.assert_called_once_with("alerts:risk_breach", data)

        # Non-SMS channel -- should not send
        mock_sms.reset_mock()
        await router._route("alerts:trade_executed", data)
        mock_sms.send.assert_not_called()

    async def test_skips_slack_when_disabled(
        self,
        mock_redis: AsyncMock,
        mock_slack: AsyncMock,
        mock_sms: AsyncMock,
        alert_config_disabled: AlertConfig,
    ) -> None:
        """Slack is not called when slack_enabled is False."""
        router = AlertRouter(
            redis=mock_redis,
            slack_notifier=mock_slack,
            sms_notifier=mock_sms,
            config=alert_config_disabled,
        )

        await router._route("alerts:trade_executed", {"symbol": "SPY"})
        mock_slack.send.assert_not_called()

    async def test_skips_sms_when_disabled(
        self,
        mock_redis: AsyncMock,
        mock_slack: AsyncMock,
        mock_sms: AsyncMock,
        alert_config_slack_only: AlertConfig,
    ) -> None:
        """SMS is not called when sms_enabled is False."""
        router = AlertRouter(
            redis=mock_redis,
            slack_notifier=mock_slack,
            sms_notifier=mock_sms,
            config=alert_config_slack_only,
        )

        await router._route("alerts:risk_breach", {"reason": "daily loss"})
        mock_sms.send.assert_not_called()

    async def test_slack_error_does_not_block_sms(
        self,
        mock_redis: AsyncMock,
        mock_sms: AsyncMock,
        alert_config_all_enabled: AlertConfig,
    ) -> None:
        """If Slack throws, SMS still gets called."""
        failing_slack = AsyncMock(spec=SlackNotifier)
        failing_slack.send.side_effect = RuntimeError("webhook down")

        router = AlertRouter(
            redis=mock_redis,
            slack_notifier=failing_slack,
            sms_notifier=mock_sms,
            config=alert_config_all_enabled,
        )

        await router._route("alerts:risk_breach", {"reason": "test"})
        # SMS should still be called despite Slack failure
        mock_sms.send.assert_called_once()

    async def test_sms_error_does_not_block_slack(
        self,
        mock_redis: AsyncMock,
        mock_slack: AsyncMock,
        alert_config_all_enabled: AlertConfig,
    ) -> None:
        """If SMS throws, Slack is still called (and already was)."""
        failing_sms = AsyncMock(spec=SMSNotifier)
        failing_sms.send.side_effect = RuntimeError("twilio down")

        router = AlertRouter(
            redis=mock_redis,
            slack_notifier=mock_slack,
            sms_notifier=failing_sms,
            config=alert_config_all_enabled,
        )

        await router._route("alerts:risk_breach", {"reason": "test"})
        # Slack should have been called
        mock_slack.send.assert_called_once()

    async def test_handles_none_notifiers(
        self,
        mock_redis: AsyncMock,
        alert_config_all_enabled: AlertConfig,
    ) -> None:
        """Router handles None notifiers gracefully (no crash)."""
        router = AlertRouter(
            redis=mock_redis,
            slack_notifier=None,
            sms_notifier=None,
            config=alert_config_all_enabled,
        )

        # Should not raise
        await router._route("alerts:trade_executed", {"symbol": "SPY"})


class TestAlertRouterChannels:
    """Tests for AlertRouter channel coverage."""

    def test_channels_covers_all_event_types(self) -> None:
        """CHANNELS list covers all 7 expected event types."""
        expected = {
            "alerts:trade_executed",
            "alerts:trade_rejected",
            "alerts:risk_breach",
            "alerts:circuit_breaker",
            "alerts:system_error",
            "alerts:approval_request",
            "alerts:approval_resolved",
        }
        assert set(AlertRouter.CHANNELS) == expected
        assert len(AlertRouter.CHANNELS) == 7


# ---------------------------------------------------------------------------
# SMSNotifier cooldown tests
# ---------------------------------------------------------------------------


class TestSMSCooldown:
    """Tests for SMSNotifier per-channel cooldown enforcement."""

    async def test_cooldown_skips_rapid_fire(self) -> None:
        """Second send within cooldown window is skipped."""
        notifier = SMSNotifier(
            account_sid="AC_TEST",
            auth_token="auth_test",
            from_number="+15551234567",
            to_number="+15559876543",
            cooldown_seconds=300,
        )

        with patch("trading.alerts.sms.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # First send should go through
            await notifier.send("alerts:risk_breach", {"reason": "test"})
            assert mock_client.post.call_count == 1

            # Second send within cooldown should be skipped
            await notifier.send("alerts:risk_breach", {"reason": "test again"})
            assert mock_client.post.call_count == 1  # Still 1

    async def test_different_channels_have_independent_cooldown(self) -> None:
        """Different channels have independent cooldowns."""
        notifier = SMSNotifier(
            account_sid="AC_TEST",
            auth_token="auth_test",
            from_number="+15551234567",
            to_number="+15559876543",
            cooldown_seconds=300,
        )

        with patch("trading.alerts.sms.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # Send on channel A
            await notifier.send("alerts:risk_breach", {"reason": "a"})
            assert mock_client.post.call_count == 1

            # Send on channel B -- different channel, should go through
            await notifier.send("alerts:circuit_breaker", {"reason": "b"})
            assert mock_client.post.call_count == 2

    async def test_send_error_does_not_update_cooldown(self) -> None:
        """Failed send does not update cooldown timestamp."""
        notifier = SMSNotifier(
            account_sid="AC_TEST",
            auth_token="auth_test",
            from_number="+15551234567",
            to_number="+15559876543",
            cooldown_seconds=300,
        )

        with patch("trading.alerts.sms.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = RuntimeError("network error")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # Failed send -- should not update cooldown
            await notifier.send("alerts:risk_breach", {"reason": "fail"})
            assert "alerts:risk_breach" not in notifier._last_sent


class TestSMSBody:
    """Tests for SMSNotifier body building."""

    def test_body_truncated_to_160(self) -> None:
        """SMS body is truncated to 160 characters."""
        notifier = SMSNotifier(
            account_sid="AC_TEST",
            auth_token="auth_test",
            from_number="+15551234567",
            to_number="+15559876543",
        )
        long_reason = "x" * 200
        body = notifier._build_body("alerts:risk_breach", {"reason": long_reason})
        assert len(body) <= 160
        assert body.endswith("...")


# ---------------------------------------------------------------------------
# SlackNotifier block tests
# ---------------------------------------------------------------------------


class TestSlackBlocks:
    """Tests for SlackNotifier Block Kit block generation."""

    def test_trade_executed_blocks(self) -> None:
        """Trade executed produces header + section with fields."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = notifier._build_blocks(
            "alerts:trade_executed",
            {
                "symbol": "SPY",
                "strategy": "iron_condor",
                "fill_price": 2.50,
                "quantity": 5,
            },
        )
        assert len(blocks) == 2
        assert blocks[0]["type"] == "header"
        assert blocks[0]["text"]["text"] == "Trade Executed"
        assert blocks[1]["type"] == "section"
        assert len(blocks[1]["fields"]) == 4

    def test_risk_breach_blocks(self) -> None:
        """Risk breach produces header + section."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = notifier._build_blocks(
            "alerts:risk_breach",
            {"reason": "daily loss exceeded", "details": "Lost $2100"},
        )
        assert len(blocks) == 2
        assert blocks[0]["text"]["text"] == "Risk Breach"
        assert "daily loss exceeded" in blocks[1]["text"]["text"]

    def test_circuit_breaker_blocks(self) -> None:
        """Circuit breaker produces header + section."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = notifier._build_blocks(
            "alerts:circuit_breaker",
            {"reason": "emergency halt triggered"},
        )
        assert len(blocks) == 2
        assert blocks[0]["text"]["text"] == "Circuit Breaker Activated"

    def test_system_error_blocks(self) -> None:
        """System error produces header + section."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = notifier._build_blocks(
            "alerts:system_error",
            {"error": "database connection lost", "component": "risk_engine"},
        )
        assert len(blocks) == 2
        assert blocks[0]["text"]["text"] == "System Error"
        assert "database connection lost" in blocks[1]["text"]["text"]

    def test_approval_request_blocks(self) -> None:
        """Approval request produces header + section with fields."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = notifier._build_blocks(
            "alerts:approval_request",
            {
                "symbol": "AAPL",
                "strategy": "vertical_spread",
                "max_loss": 750,
                "approval_id": "abc-123",
            },
        )
        assert len(blocks) == 4  # header + 2 sections + actions
        assert blocks[0]["text"]["text"] == "Trade Approval Required"
        assert blocks[1]["type"] == "section"
        assert len(blocks[1]["fields"]) == 4
        # Actions block with approve/reject buttons
        assert blocks[3]["type"] == "actions"
        action_ids = [e["action_id"] for e in blocks[3]["elements"]]
        assert "approve_trade" in action_ids
        assert "reject_trade" in action_ids

    def test_approval_resolved_blocks(self) -> None:
        """Approval resolved produces header + section."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = notifier._build_blocks(
            "alerts:approval_resolved",
            {"decision": "approved", "approval_id": "abc-123"},
        )
        assert len(blocks) == 2
        assert "Approved" in blocks[0]["text"]["text"]

    def test_unknown_channel_blocks(self) -> None:
        """Unknown channel produces a generic section block."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = notifier._build_blocks(
            "alerts:unknown_type",
            {"key": "value"},
        )
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"

    def test_all_known_channels_produce_blocks(self) -> None:
        """All known alert channels produce valid Block Kit blocks."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        known_channels = [
            "alerts:trade_executed",
            "alerts:risk_breach",
            "alerts:circuit_breaker",
            "alerts:system_error",
            "alerts:approval_request",
            "alerts:approval_resolved",
        ]
        for channel in known_channels:
            blocks = notifier._build_blocks(channel, {"test": True})
            assert len(blocks) >= 1, f"No blocks for {channel}"
            # All should have a header block
            assert blocks[0]["type"] == "header", f"No header for {channel}"
