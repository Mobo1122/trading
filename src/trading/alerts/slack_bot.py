"""Slack bot with Socket Mode for interactive trade approval buttons.

Provides a slack-bolt AsyncApp running in Socket Mode that handles
approve/reject button clicks from Slack messages. Action handlers
resolve approvals via ApprovalManager and update the original Slack
message to show the decision result.

Socket Mode uses a WebSocket connection from the app to Slack,
eliminating the need for a public HTTP endpoint -- ideal for a
trading system running behind a firewall.

Action handlers call ack() as the first line (within the 3-second
Slack deadline) and then perform async work (resolve, message update)
in a try/except block so failures after ack are non-fatal.
"""

from __future__ import annotations

from typing import Any

import structlog
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.app.async_app import AsyncApp

log = structlog.get_logger(component="slack_bot")


def _build_resolved_blocks(
    original_blocks: list[dict], decision: str
) -> list[dict]:
    """Replace the actions block with a context block showing the resolution.

    Keeps header and section blocks (trade details) unchanged. The
    actions block (type="actions") is replaced with a context block
    displaying the decision status.

    Args:
        original_blocks: Original Slack message blocks.
        decision: Resolution decision ("approved", "rejected", or "timed_out").

    Returns:
        Updated blocks list with actions replaced by decision context.
    """
    decision_text = {
        "approved": ":white_check_mark: *Approved* by user via Slack",
        "rejected": ":x: *Rejected* by user via Slack",
        "timed_out": ":clock3: *Timed out* - auto-rejected",
    }

    resolved_blocks: list[dict] = []
    for block in original_blocks:
        if block.get("type") == "actions":
            # Replace actions block with context showing decision
            resolved_blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": decision_text.get(
                                decision,
                                f":grey_question: *{decision}*",
                            ),
                        },
                    ],
                }
            )
        else:
            resolved_blocks.append(block)

    return resolved_blocks


def create_slack_bot(
    bot_token: str, approval_manager: Any
) -> AsyncApp:
    """Create a slack-bolt AsyncApp with approve/reject action handlers.

    Registers ``approve_trade`` and ``reject_trade`` action handlers
    that resolve approvals via the ApprovalManager and update the
    original Slack message to show the decision.

    Args:
        bot_token: Slack bot token (xoxb-*).
        approval_manager: ApprovalManager instance for resolving approvals.

    Returns:
        Configured AsyncApp ready for Socket Mode.
    """
    app = AsyncApp(token=bot_token)

    @app.action("approve_trade")
    async def handle_approve(ack: Any, body: dict, client: Any) -> None:
        """Handle approve button click -- ack first, then resolve."""
        await ack()

        try:
            approval_id = body["actions"][0]["value"]
            await approval_manager.resolve(approval_id, "approved")

            await client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                blocks=_build_resolved_blocks(
                    body["message"]["blocks"], "approved"
                ),
                text="Trade approved",
            )

            log.info(
                "action.approve_trade",
                approval_id=approval_id,
            )
        except Exception:
            log.warning("action.approve_trade.failed", exc_info=True)

    @app.action("reject_trade")
    async def handle_reject(ack: Any, body: dict, client: Any) -> None:
        """Handle reject button click -- ack first, then resolve."""
        await ack()

        try:
            approval_id = body["actions"][0]["value"]
            await approval_manager.resolve(approval_id, "rejected")

            await client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                blocks=_build_resolved_blocks(
                    body["message"]["blocks"], "rejected"
                ),
                text="Trade rejected",
            )

            log.info(
                "action.reject_trade",
                approval_id=approval_id,
            )
        except Exception:
            log.warning("action.reject_trade.failed", exc_info=True)

    return app


async def start_socket_mode(app: AsyncApp, app_token: str) -> None:
    """Start the Slack bot in Socket Mode.

    Creates an AsyncSocketModeHandler and starts listening for
    events via WebSocket. Runs indefinitely until cancelled.

    Args:
        app: Configured AsyncApp with action handlers.
        app_token: Slack app-level token (xapp-*) for Socket Mode.
    """
    handler = AsyncSocketModeHandler(app, app_token)
    log.info("socket_mode.starting")
    await handler.start_async()
