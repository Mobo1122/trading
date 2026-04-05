"""Slack notification via incoming webhook with Block Kit formatting.

Sends formatted alert messages to Slack using AsyncWebhookClient.
Messages are formatted with Block Kit blocks for rich display based
on the alert channel type (trade events, risk breaches, system errors).

All Slack operations are non-fatal: errors are logged as warnings
but never raised, following the established project convention.
"""

from __future__ import annotations

import json

import structlog
from slack_sdk.webhook.async_client import AsyncWebhookClient

logger = structlog.get_logger().bind(component="slack_notifier")


class SlackNotifier:
    """Sends formatted alert messages to Slack via incoming webhook.

    Builds Block Kit blocks based on channel type for rich message
    formatting. Falls back to plain text for unknown channel types.

    Args:
        webhook_url: Slack incoming webhook URL.
    """

    def __init__(self, webhook_url: str) -> None:
        self._client = AsyncWebhookClient(url=webhook_url)

    async def send(self, channel: str, data: dict) -> None:
        """Send a formatted alert message to Slack.

        Builds Block Kit blocks appropriate for the channel type and
        sends via the webhook client. Errors are caught and logged
        as warnings (non-fatal).

        Args:
            channel: Redis pub/sub channel name (e.g. "alerts:trade_executed").
            data: Event payload dictionary.
        """
        text = self._build_text(channel, data)
        blocks = self._build_blocks(channel, data)

        try:
            response = await self._client.send(text=text, blocks=blocks)
            if response.status_code != 200:
                logger.warning(
                    "slack.send_failed",
                    channel=channel,
                    status_code=response.status_code,
                    body=response.body,
                )
        except Exception as exc:
            logger.warning(
                "slack.send_error",
                channel=channel,
                error=str(exc),
            )

    def _build_text(self, channel: str, data: dict) -> str:
        """Build a plain-text fallback for the Slack message.

        Args:
            channel: Redis pub/sub channel name.
            data: Event payload dictionary.

        Returns:
            Plain-text summary string.
        """
        channel_short = channel.replace("alerts:", "")

        if channel == "alerts:trade_executed":
            symbol = data.get("symbol", "?")
            strategy = data.get("strategy", "?")
            return f"Trade Executed: {symbol} ({strategy})"

        if channel == "alerts:risk_breach":
            reason = data.get("reason", "unknown")
            return f"Risk Breach: {reason}"

        if channel == "alerts:circuit_breaker":
            reason = data.get("reason", "unknown")
            return f"Circuit Breaker Activated: {reason}"

        if channel == "alerts:system_error":
            error = data.get("error", "unknown")
            return f"System Error: {error}"

        if channel == "alerts:approval_request":
            symbol = data.get("symbol", "?")
            strategy = data.get("strategy", "?")
            return f"Approval Required: {symbol} ({strategy})"

        if channel == "alerts:approval_resolved":
            decision = data.get("decision", "?")
            approval_id = data.get("approval_id", "?")
            return f"Approval Resolved: {approval_id} -> {decision}"

        return f"[{channel_short}] {json.dumps(data, default=str)[:200]}"

    def _build_blocks(self, channel: str, data: dict) -> list[dict]:
        """Build Block Kit blocks for the Slack message.

        Returns structured blocks with appropriate colors and fields
        based on the alert channel type.

        Args:
            channel: Redis pub/sub channel name.
            data: Event payload dictionary.

        Returns:
            List of Block Kit block dicts.
        """
        if channel == "alerts:trade_executed":
            return self._blocks_trade_executed(data)
        if channel == "alerts:risk_breach":
            return self._blocks_risk_breach(data)
        if channel == "alerts:circuit_breaker":
            return self._blocks_circuit_breaker(data)
        if channel == "alerts:system_error":
            return self._blocks_system_error(data)
        if channel == "alerts:approval_request":
            return self._blocks_approval_request(data)
        if channel == "alerts:approval_resolved":
            return self._blocks_approval_resolved(data)

        # Default: plain section with data summary
        channel_short = channel.replace("alerts:", "")
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*[{channel_short}]*\n```{json.dumps(data, default=str, indent=2)[:500]}```",
                },
            },
        ]

    def _blocks_trade_executed(self, data: dict) -> list[dict]:
        """Build blocks for a trade execution alert."""
        symbol = data.get("symbol", "?")
        strategy = data.get("strategy", "?")
        fill_price = data.get("fill_price", "?")
        quantity = data.get("quantity", "?")
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Trade Executed",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Symbol:* {symbol}"},
                    {"type": "mrkdwn", "text": f"*Strategy:* {strategy}"},
                    {"type": "mrkdwn", "text": f"*Fill Price:* {fill_price}"},
                    {"type": "mrkdwn", "text": f"*Quantity:* {quantity}"},
                ],
            },
        ]

    def _blocks_risk_breach(self, data: dict) -> list[dict]:
        """Build blocks for a risk breach alert."""
        reason = data.get("reason", "unknown")
        details = data.get("details", "")
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Risk Breach",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Reason:* {reason}\n{details}",
                },
            },
        ]

    def _blocks_circuit_breaker(self, data: dict) -> list[dict]:
        """Build blocks for a circuit breaker alert."""
        reason = data.get("reason", "unknown")
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Circuit Breaker Activated",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Halt Reason:* {reason}",
                },
            },
        ]

    def _blocks_system_error(self, data: dict) -> list[dict]:
        """Build blocks for a system error alert."""
        error = data.get("error", "unknown")
        component = data.get("component", "")
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "System Error",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error:* {error}" + (f"\n*Component:* {component}" if component else ""),
                },
            },
        ]

    def _blocks_approval_request(self, data: dict) -> list[dict]:
        """Build blocks for an approval request alert."""
        symbol = data.get("symbol", "?")
        strategy = data.get("strategy", "?")
        max_loss = data.get("max_loss", "?")
        approval_id = data.get("approval_id", "?")
        return [
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
                    {"type": "mrkdwn", "text": f"*Symbol:* {symbol}"},
                    {"type": "mrkdwn", "text": f"*Strategy:* {strategy}"},
                    {"type": "mrkdwn", "text": f"*Max Loss:* ${max_loss}"},
                    {"type": "mrkdwn", "text": f"*Approval ID:* {approval_id}"},
                ],
            },
        ]

    def _blocks_approval_resolved(self, data: dict) -> list[dict]:
        """Build blocks for an approval resolution alert."""
        decision = data.get("decision", "?")
        approval_id = data.get("approval_id", "?")
        emoji = ":white_check_mark:" if decision == "approved" else ":x:"
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Approval Resolved: {decision.title()}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *Approval ID:* {approval_id}\n*Decision:* {decision}",
                },
            },
        ]
