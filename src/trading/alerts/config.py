"""Alert and auto-execute configuration models.

Defines Pydantic models for:
  - AlertConfig: Slack and SMS notification settings (webhook URLs, tokens,
    Twilio credentials, channel filtering, cooldowns).
  - AutoExecuteThresholds: Per-mode thresholds below which trades auto-execute
    without human approval.
  - AutoExecuteConfig: Paper/live threshold separation matching the
    established risk_limits pattern.

These models are loaded from YAML via the Settings class in trading.config.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AutoExecuteThresholds(BaseModel):
    """Thresholds below which trades auto-execute without approval.

    Trades exceeding any threshold are escalated for human approval.
    Paper thresholds are relaxed (2x live) to reduce friction during testing.

    Attributes:
        max_loss_dollars: Max potential loss above which approval is required.
        max_delta_impact: Max delta change above which approval is required.
        max_vega_impact: Max vega change above which approval is required.
        approval_timeout_seconds: Seconds to wait for approval before auto-reject.
    """

    max_loss_dollars: float = Field(default=500.0, gt=0)
    max_delta_impact: float = Field(default=50.0, gt=0)
    max_vega_impact: float = Field(default=100.0, gt=0)
    approval_timeout_seconds: int = Field(default=300, gt=30, le=3600)


class AutoExecuteConfig(BaseModel):
    """Auto-execute configuration with paper/live threshold separation.

    Follows the established risk_limits pattern: paper thresholds are
    relaxed (2x live) to reduce approval friction during testing.

    Attributes:
        paper: Relaxed thresholds for paper trading.
        live: Strict thresholds for live trading.
    """

    paper: AutoExecuteThresholds = Field(
        default_factory=lambda: AutoExecuteThresholds(
            max_loss_dollars=2000.0,
            max_delta_impact=200.0,
            max_vega_impact=400.0,
        )
    )
    live: AutoExecuteThresholds = Field(default_factory=AutoExecuteThresholds)


class AlertConfig(BaseModel):
    """Alert notification configuration for Slack and SMS channels.

    Controls which notification channels are active and their credentials.
    Disabled notifiers are gracefully skipped (no crash if unconfigured).

    Attributes:
        slack_enabled: Whether to send Slack notifications.
        slack_webhook_url: Incoming webhook URL for outgoing alert messages.
        slack_bot_token: xoxb-* token for Socket Mode / chat.update.
        slack_app_token: xapp-* token for Socket Mode connections.
        slack_channel: Default Slack channel for alerts.
        sms_enabled: Whether to send SMS notifications.
        twilio_account_sid: Twilio account SID for SMS API.
        twilio_auth_token: Twilio auth token for SMS API.
        twilio_from_number: Twilio phone number to send SMS from.
        twilio_to_number: Phone number to receive SMS alerts.
        sms_channels: Redis pub/sub channels that trigger SMS (high-severity only).
        sms_cooldown_seconds: Per-channel cooldown between SMS messages.
    """

    slack_enabled: bool = False
    slack_webhook_url: str = ""
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channel: str = "#trading-alerts"
    sms_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_to_number: str = ""
    sms_channels: list[str] = [
        "alerts:risk_breach",
        "alerts:circuit_breaker",
        "alerts:system_error",
    ]
    sms_cooldown_seconds: int = 300
