"""SMS notification via Twilio REST API with per-channel cooldown.

Sends concise SMS messages for high-severity alert channels using
httpx async HTTP client to POST to the Twilio Messages API.
Per-channel cooldown prevents rapid-fire SMS from flurries of events.

All SMS operations are non-fatal: errors are logged as warnings
but never raised, following the established project convention.
"""

from __future__ import annotations

import time

import httpx
import structlog

logger = structlog.get_logger().bind(component="sms_notifier")

# Twilio Messages API endpoint template
_TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

# Max SMS segment length (single segment)
_MAX_SMS_LENGTH = 160


class SMSNotifier:
    """Sends SMS alerts via Twilio REST API with per-channel cooldown.

    Uses httpx async client to POST to Twilio's Messages API. Tracks
    last-sent timestamps per channel to enforce cooldown windows,
    preventing SMS floods from rapid-fire events.

    Args:
        account_sid: Twilio account SID.
        auth_token: Twilio auth token.
        from_number: Twilio phone number to send from.
        to_number: Phone number to receive SMS alerts.
        cooldown_seconds: Minimum seconds between SMS per channel.
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_number: str,
        cooldown_seconds: int = 300,
    ) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._to_number = to_number
        self._cooldown = cooldown_seconds
        self._last_sent: dict[str, float] = {}

    async def send(self, channel: str, data: dict) -> None:
        """Send an SMS alert for the given channel event.

        Checks cooldown window before sending. If a message was sent
        for this channel within the cooldown period, the send is
        skipped. Errors are caught and logged as warnings (non-fatal).

        Args:
            channel: Redis pub/sub channel name (e.g. "alerts:risk_breach").
            data: Event payload dictionary.
        """
        # Check cooldown
        now = time.monotonic()
        last = self._last_sent.get(channel)
        if last is not None and (now - last) < self._cooldown:
            logger.debug(
                "sms.cooldown_active",
                channel=channel,
                remaining=round(self._cooldown - (now - last), 1),
            )
            return

        body = self._build_body(channel, data)
        url = _TWILIO_URL.format(account_sid=self._account_sid)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    auth=(self._account_sid, self._auth_token),
                    data={
                        "To": self._to_number,
                        "From": self._from_number,
                        "Body": body,
                    },
                )
                response.raise_for_status()

            self._last_sent[channel] = time.monotonic()
            logger.info(
                "sms.sent",
                channel=channel,
                body_length=len(body),
            )
        except Exception as exc:
            logger.warning(
                "sms.send_error",
                channel=channel,
                error=str(exc),
            )

    def _build_body(self, channel: str, data: dict) -> str:
        """Build a concise SMS body from channel and event data.

        Truncates to 160 characters (single SMS segment) with "..."
        suffix if the message exceeds the limit.

        Args:
            channel: Redis pub/sub channel name.
            data: Event payload dictionary.

        Returns:
            SMS body string, max 160 characters.
        """
        channel_short = channel.replace("alerts:", "").upper()

        if channel == "alerts:risk_breach":
            reason = data.get("reason", "unknown")
            body = f"[{channel_short}] {reason}"
        elif channel == "alerts:circuit_breaker":
            reason = data.get("reason", "unknown")
            body = f"[{channel_short}] Halt: {reason}"
        elif channel == "alerts:system_error":
            error = data.get("error", "unknown")
            body = f"[{channel_short}] {error}"
        else:
            summary = ", ".join(f"{k}={v}" for k, v in list(data.items())[:5])
            body = f"[{channel_short}] {summary}"

        if len(body) > _MAX_SMS_LENGTH:
            body = body[: _MAX_SMS_LENGTH - 3] + "..."

        return body
