"""Alert router: Redis pub/sub consumer that fans out to notification channels.

Subscribes to Redis pub/sub alert channels and routes events to configured
notifiers (Slack, SMS). Each notifier is called independently with its own
error handling so one notifier failure does not block the other.

Follows the established RedisBridge pattern from Phase 7 for Redis pub/sub
consumption with clean shutdown on cancellation.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from trading.alerts.config import AlertConfig
from trading.alerts.slack import SlackNotifier
from trading.alerts.sms import SMSNotifier

logger = structlog.get_logger().bind(component="alert_router")


class AlertRouter:
    """Consumes Redis pub/sub events and routes to notification channels.

    Subscribes to predefined alert channels and fans out events to
    Slack and SMS notifiers based on configuration. Missing or disabled
    notifiers are gracefully skipped.

    Args:
        redis: Async Redis client instance.
        slack_notifier: SlackNotifier instance, or None if Slack not configured.
        sms_notifier: SMSNotifier instance, or None if SMS not configured.
        config: AlertConfig with enabled flags and channel filtering.
    """

    CHANNELS: list[str] = [
        "alerts:trade_executed",
        "alerts:trade_rejected",
        "alerts:risk_breach",
        "alerts:circuit_breaker",
        "alerts:system_error",
        "alerts:approval_request",
        "alerts:approval_resolved",
    ]

    def __init__(
        self,
        redis: Any,
        slack_notifier: SlackNotifier | None,
        sms_notifier: SMSNotifier | None,
        config: AlertConfig,
    ) -> None:
        self._redis = redis
        self._slack = slack_notifier
        self._sms = sms_notifier
        self._config = config

    async def listen(self) -> None:
        """Subscribe to alert channels and route messages to notifiers.

        Runs indefinitely until cancelled. On cancellation, cleanly
        unsubscribes and closes the pubsub connection.
        """
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(*self.CHANNELS)
            logger.info(
                "alert_router.subscribed",
                channels=self.CHANNELS,
            )

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                raw_data = message["data"]
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode()

                try:
                    data = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "alert_router.invalid_json",
                        channel=channel,
                        data=str(raw_data)[:200],
                    )
                    continue

                await self._route(channel, data)

        except asyncio.CancelledError:
            logger.info("alert_router.shutting_down")
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception:
                pass
            raise

    async def _route(self, channel: str, data: dict) -> None:
        """Route an alert event to configured notifiers.

        Each notifier is called independently with its own try/except
        so one failure does not block the other.

        Args:
            channel: Redis pub/sub channel name.
            data: Parsed event payload dictionary.
        """
        if self._slack is not None and self._config.slack_enabled:
            try:
                await self._slack.send(channel, data)
            except Exception as exc:
                logger.warning(
                    "alert_router.slack_error",
                    channel=channel,
                    error=str(exc),
                )

        if (
            self._sms is not None
            and self._config.sms_enabled
            and channel in self._config.sms_channels
        ):
            try:
                await self._sms.send(channel, data)
            except Exception as exc:
                logger.warning(
                    "alert_router.sms_error",
                    channel=channel,
                    error=str(exc),
                )
