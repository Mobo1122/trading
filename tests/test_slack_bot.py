"""Unit tests for Slack bot action handlers and SlackNotifier interactive buttons.

Tests cover:
  - approve_trade action handler calls ack, resolve, chat_update
  - reject_trade action handler calls ack, resolve, chat_update
  - _build_resolved_blocks replaces actions block with approved context
  - _build_resolved_blocks replaces actions block with timed_out context
  - SlackNotifier approval request blocks contain approve/reject buttons
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from trading.alerts.slack import SlackNotifier
from trading.alerts.slack_bot import _build_resolved_blocks, create_slack_bot


def _make_action_body(action_id: str, approval_id: str) -> dict:
    """Build a minimal Slack action body for testing."""
    return {
        "actions": [
            {
                "action_id": action_id,
                "value": approval_id,
            }
        ],
        "channel": {"id": "C123"},
        "message": {
            "ts": "1234567890.123456",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Trade Approval Required",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": "*Symbol:* AAPL"},
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "approve_trade",
                            "value": approval_id,
                        },
                        {
                            "type": "button",
                            "action_id": "reject_trade",
                            "value": approval_id,
                        },
                    ],
                },
            ],
        },
    }


def _get_handler(app, handler_name: str):
    """Extract a registered handler function from an AsyncApp by name."""
    for listener in app._async_listeners:
        func = listener.ack_function
        if func.__name__ == handler_name:
            return func
    return None


SAMPLE_BLOCKS = [
    {
        "type": "header",
        "text": {"type": "plain_text", "text": "Trade Approval Required"},
    },
    {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": "*Symbol:* AAPL"}],
    },
    {
        "type": "actions",
        "elements": [
            {"type": "button", "action_id": "approve_trade", "value": "test-1"},
            {"type": "button", "action_id": "reject_trade", "value": "test-1"},
        ],
    },
]


class TestApproveActionHandler:
    """Tests for the approve_trade action handler."""

    @pytest.mark.asyncio
    async def test_approve_action_handler_calls_resolve(self) -> None:
        """Approve handler calls ack first, then resolve, then chat_update."""
        approval_manager = AsyncMock()
        approval_manager.resolve = AsyncMock(return_value=True)

        app = create_slack_bot(
            bot_token="xoxb-test-token",
            approval_manager=approval_manager,
        )

        handler = _get_handler(app, "handle_approve")
        assert handler is not None, "approve_trade handler not registered"

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("approve_trade", "approval-123")

        await handler(ack=ack, body=body, client=client)

        # Verify ack was called
        ack.assert_awaited_once()

        # Verify resolve was called with correct args
        approval_manager.resolve.assert_awaited_once_with(
            "approval-123", "approved"
        )

        # Verify chat_update was called
        client.chat_update.assert_awaited_once()
        call_kwargs = client.chat_update.call_args[1]
        assert call_kwargs["channel"] == "C123"
        assert call_kwargs["ts"] == "1234567890.123456"
        assert call_kwargs["text"] == "Trade approved"


class TestRejectActionHandler:
    """Tests for the reject_trade action handler."""

    @pytest.mark.asyncio
    async def test_reject_action_handler_calls_resolve(self) -> None:
        """Reject handler calls ack first, then resolve, then chat_update."""
        approval_manager = AsyncMock()
        approval_manager.resolve = AsyncMock(return_value=True)

        app = create_slack_bot(
            bot_token="xoxb-test-token",
            approval_manager=approval_manager,
        )

        handler = _get_handler(app, "handle_reject")
        assert handler is not None, "reject_trade handler not registered"

        ack = AsyncMock()
        client = AsyncMock()
        body = _make_action_body("reject_trade", "approval-456")

        await handler(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        approval_manager.resolve.assert_awaited_once_with(
            "approval-456", "rejected"
        )
        client.chat_update.assert_awaited_once()
        call_kwargs = client.chat_update.call_args[1]
        assert call_kwargs["text"] == "Trade rejected"


class TestBuildResolvedBlocks:
    """Tests for _build_resolved_blocks helper."""

    def test_build_resolved_blocks_replaces_actions(self) -> None:
        """Approved decision replaces actions block with context block."""
        result = _build_resolved_blocks(SAMPLE_BLOCKS, "approved")

        # Header and section should be kept
        assert result[0]["type"] == "header"
        assert result[1]["type"] == "section"

        # Actions block should be replaced with context
        assert result[2]["type"] == "context"
        text = result[2]["elements"][0]["text"]
        assert "Approved" in text
        assert "white_check_mark" in text

    def test_build_resolved_blocks_timed_out(self) -> None:
        """Timed out decision replaces actions block with timeout message."""
        result = _build_resolved_blocks(SAMPLE_BLOCKS, "timed_out")

        assert result[2]["type"] == "context"
        text = result[2]["elements"][0]["text"]
        assert "Timed out" in text
        assert "clock3" in text


class TestSlackNotifierApprovalBlocks:
    """Tests for SlackNotifier approval request Block Kit output."""

    def test_slack_notifier_approval_blocks_have_buttons(self) -> None:
        """Approval request blocks contain approve/reject interactive buttons."""
        notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        blocks = notifier._build_blocks(
            "alerts:approval_request",
            {
                "symbol": "SPY",
                "strategy": "iron_condor",
                "max_loss": 1200,
                "max_profit": 350,
                "delta": 25.5,
                "theta": -8.2,
                "vega": 42.0,
                "timeout_minutes": 5,
                "approval_id": "test-approval-789",
                "requested_at": "2026-04-05T12:00:00Z",
            },
        )

        # Find the actions block
        actions_block = None
        for block in blocks:
            if block.get("type") == "actions":
                actions_block = block
                break

        assert actions_block is not None, "No actions block found"

        elements = actions_block["elements"]
        assert len(elements) == 2

        # Check approve button
        approve = elements[0]
        assert approve["action_id"] == "approve_trade"
        assert approve["style"] == "primary"
        assert approve["value"] == "test-approval-789"

        # Check reject button
        reject = elements[1]
        assert reject["action_id"] == "reject_trade"
        assert reject["style"] == "danger"
        assert reject["value"] == "test-approval-789"
