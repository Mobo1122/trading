"""Slack notification via incoming webhook with Block Kit formatting.

Sends formatted alert messages to Slack using AsyncWebhookClient.
Messages are formatted with Block Kit blocks for rich display based
on the alert channel type (trade events, risk breaches, system errors).

For approval request messages, interactive buttons (approve/reject)
are sent via ``chat.postMessage`` using the bot token instead of the
webhook, because incoming webhooks do not support interactive
``action_id`` buttons. Other channels continue using the webhook.

All Slack operations are non-fatal: errors are logged as warnings
but never raised, following the established project convention.
"""

from __future__ import annotations

import json

import structlog
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.webhook.async_client import AsyncWebhookClient

logger = structlog.get_logger().bind(component="slack_notifier")


class SlackNotifier:
    """Sends formatted alert messages to Slack via incoming webhook.

    Builds Block Kit blocks based on channel type for rich message
    formatting. Falls back to plain text for unknown channel types.

    For approval request messages with interactive buttons, uses
    ``chat.postMessage`` via the bot token (``AsyncWebClient``).
    All other messages use the incoming webhook.

    Args:
        webhook_url: Slack incoming webhook URL.
        bot_token: Optional Slack bot token (xoxb-*) for interactive messages.
        channel: Slack channel for chat.postMessage (e.g. "#trading-alerts").
    """

    def __init__(
        self,
        webhook_url: str,
        bot_token: str | None = None,
        channel: str = "",
    ) -> None:
        self._client = AsyncWebhookClient(url=webhook_url)
        self._web_client: AsyncWebClient | None = None
        self._channel = channel
        if bot_token:
            self._web_client = AsyncWebClient(token=bot_token)

    async def send(self, channel: str, data: dict) -> None:
        """Send a formatted alert message to Slack.

        Builds Block Kit blocks appropriate for the channel type and
        sends via the appropriate client. Approval request messages
        with interactive buttons use ``chat.postMessage`` (bot token)
        when available; all other messages use the incoming webhook.

        Args:
            channel: Redis pub/sub channel name (e.g. "alerts:trade_executed").
            data: Event payload dictionary.
        """
        text = self._build_text(channel, data)
        blocks = self._build_blocks(channel, data)

        try:
            # Approval requests with interactive buttons need chat.postMessage
            if (
                channel == "alerts:approval_request"
                and self._web_client is not None
                and self._channel
            ):
                await self._web_client.chat_postMessage(
                    channel=self._channel,
                    blocks=blocks,
                    text=text,
                )
            else:
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

        if channel == "alerts:trade_rejected":
            symbol = data.get("symbol", "")
            symbols = data.get("symbols", [])
            display_symbol = symbol or (", ".join(symbols) if symbols else "?")
            reason = data.get("reason", "unknown")
            return f"Trade Rejected: {display_symbol} ({reason})"

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
        if channel == "alerts:trade_rejected":
            return self._blocks_trade_rejected(data)

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
        """Build blocks for an approval request with interactive buttons.

        Includes trade context fields and approve/reject buttons with
        ``action_id`` values that the Slack bot Socket Mode handler
        listens for.
        """
        symbol = data.get("symbol", "?")
        strategy = data.get("strategy", "?")
        max_loss = data.get("max_loss", "?")
        max_profit = data.get("max_profit", "?")
        delta = data.get("delta", 0)
        theta = data.get("theta", 0)
        vega = data.get("vega", 0)
        timeout_minutes = data.get("timeout_minutes", "5")
        approval_id = data.get("approval_id", "?")
        requested_at = data.get("requested_at", "")

        blocks: list[dict] = [
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
                    {"type": "mrkdwn", "text": f"*Max Profit:* ${max_profit}"},
                ],
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Delta Impact:* {delta}"},
                    {"type": "mrkdwn", "text": f"*Theta Impact:* {theta}"},
                    {"type": "mrkdwn", "text": f"*Vega Impact:* {vega}"},
                    {"type": "mrkdwn", "text": f"*Timeout:* {timeout_minutes}m"},
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Approve",
                        },
                        "style": "primary",
                        "action_id": "approve_trade",
                        "value": str(approval_id),
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Reject",
                        },
                        "style": "danger",
                        "action_id": "reject_trade",
                        "value": str(approval_id),
                    },
                ],
            },
        ]

        if requested_at:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Requested at {requested_at}",
                        },
                    ],
                }
            )

        return blocks

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

    def _blocks_trade_rejected(self, data: dict) -> list[dict]:
        """Build blocks for a trade rejection alert.

        Handles two payload shapes:
        - Executor rejection: {symbol, reason, status, run_id}
        - Approval rejection: {approval_id, reason, symbols, run_id}
        """
        # Handle both executor (symbol singular) and approval (symbols list) payloads
        symbol = data.get("symbol", "")
        symbols = data.get("symbols", [])
        display_symbol = symbol or (", ".join(symbols) if symbols else "?")
        reason = data.get("reason", "unknown")
        status = data.get("status", "")
        approval_id = data.get("approval_id", "")
        run_id = data.get("run_id", "")

        fields = [
            {"type": "mrkdwn", "text": f"*Symbol:* {display_symbol}"},
            {"type": "mrkdwn", "text": f"*Reason:* {reason}"},
        ]
        if status:
            fields.append({"type": "mrkdwn", "text": f"*Status:* {status}"})
        if approval_id:
            fields.append({"type": "mrkdwn", "text": f"*Approval ID:* {approval_id}"})

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Trade Rejected",
                },
            },
            {
                "type": "section",
                "fields": fields,
            },
        ]

        if run_id:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Run: {run_id}",
                        },
                    ],
                }
            )

        return blocks
