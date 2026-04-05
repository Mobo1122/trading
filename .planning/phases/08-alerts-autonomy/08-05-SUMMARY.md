---
phase: 08-alerts-autonomy
plan: 05
subsystem: slack-interactive
tags: [slack-bolt, socket-mode, block-kit, interactive-buttons, approval-workflow]

dependency_graph:
  requires:
    - phase: 08-01
      provides: SlackNotifier, AlertRouter, AlertConfig with bot_token/app_token fields
    - phase: 08-02
      provides: ApprovalManager with resolve() method
    - phase: 08-03
      provides: Pipeline approval gate, TradingApp alert wiring
  provides:
    - Slack bot AsyncApp with Socket Mode for approve/reject button handling
    - Enhanced SlackNotifier with Block Kit interactive buttons via chat.postMessage
    - TradingApp Slack bot lifecycle (start in connect_ib, cancel in shutdown)
  affects: []

tech_stack:
  added: []
  patterns:
    - "slack-bolt AsyncApp with Socket Mode for bidirectional Slack integration (no public HTTP endpoint)"
    - "ack() first in all action handlers (3-second Slack deadline)"
    - "chat.postMessage via AsyncWebClient for interactive button messages (webhooks cannot send action_id buttons)"
    - "_build_resolved_blocks replaces actions block with decision context on resolution"

file_tracking:
  created:
    - src/trading/alerts/slack_bot.py
    - tests/test_slack_bot.py
  modified:
    - src/trading/alerts/slack.py
    - src/trading/app.py
    - tests/test_alert_router.py

decisions:
  - id: 08-05-chat-postmessage
    description: "Approval request messages sent via chat.postMessage (bot token) not webhook, because webhooks cannot send interactive action_id buttons"
    rationale: "Slack API requirement: interactive buttons need bot token and chat.postMessage; webhook only supports static Block Kit"
  - id: 08-05-handler-extraction
    description: "Action handlers registered as closures inside create_slack_bot() capturing approval_manager"
    rationale: "slack-bolt @app.action decorator requires function registration; closure captures dependencies cleanly without global state"

metrics:
  duration: 6min
  completed: 2026-04-05
  tests_passed: 5
  tests_total: 5
---

# Phase 8 Plan 5: Slack Interactive Buttons Summary

**Slack bot with Socket Mode handling approve/reject button clicks via slack-bolt AsyncApp, enhanced SlackNotifier with Block Kit interactive buttons sent via chat.postMessage, and TradingApp lifecycle wiring**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-05T11:35:01Z
- **Completed:** 2026-04-05T11:41:07Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

### Slack Bot (`src/trading/alerts/slack_bot.py` - 157 lines)

- `create_slack_bot(bot_token, approval_manager)` creates an AsyncApp with two action handlers
- `@app.action("approve_trade")` handler: ack() first, then resolve("approved"), then chat_update with resolved blocks
- `@app.action("reject_trade")` handler: ack() first, then resolve("rejected"), then chat_update with resolved blocks
- `_build_resolved_blocks(blocks, decision)` replaces the actions block with a context block showing the decision (green check for approved, red X for rejected, clock for timed_out)
- `start_socket_mode(app, app_token)` creates AsyncSocketModeHandler and runs indefinitely via start_async()
- Post-ack work wrapped in try/except (non-fatal after ack)
- structlog with component="slack_bot"

### Enhanced SlackNotifier (`src/trading/alerts/slack.py` - 370 lines)

- Added `bot_token` and `channel` optional params to `__init__`
- When `bot_token` provided, creates `AsyncWebClient` for interactive messages
- Approval request blocks now include full trade context: symbol, strategy, max_loss, max_profit, delta/theta/vega impact, timeout, and requested_at timestamp
- Actions block with "Approve" (style=primary, action_id=approve_trade) and "Reject" (style=danger, action_id=reject_trade) buttons, with approval_id as the value
- `send()` routes approval_request messages to chat.postMessage (bot token) when web_client available; all other channels use webhook

### TradingApp Wiring (`src/trading/app.py` - 677 lines)

- Import `create_slack_bot`, `start_socket_mode` from `trading.alerts.slack_bot`
- `_slack_bot_task` instance variable initialized in `__init__`
- SlackNotifier created with `bot_token` and `channel` params in `startup()`
- Slack bot started as background task in `connect_ib()` when `slack_bot_token`, `slack_app_token`, and `approval_manager` all configured
- Slack bot task cancelled cleanly in `shutdown()` before alert router (try/except with CancelledError handling)

### Unit Tests (`tests/test_slack_bot.py` - 237 lines, 5 tests)

- `test_approve_action_handler_calls_resolve`: Verifies ack called, resolve("approved"), chat_update with "Trade approved"
- `test_reject_action_handler_calls_resolve`: Verifies ack called, resolve("rejected"), chat_update with "Trade rejected"
- `test_build_resolved_blocks_replaces_actions`: Actions block replaced with context showing "Approved" + checkmark
- `test_build_resolved_blocks_timed_out`: Actions block replaced with context showing "Timed out" + clock
- `test_slack_notifier_approval_blocks_have_buttons`: Approval request blocks contain actions block with approve_trade/reject_trade buttons with correct styles and approval_id values

## Task Commits

Each task was committed atomically:

1. **Task 1: Slack Bot with Socket Mode and enhanced SlackNotifier Block Kit buttons** - `030bdb8` (feat)
2. **Task 2: Wire Slack bot into TradingApp and unit tests** - `da7abfa` (feat)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated existing test_approval_request_blocks test**
- **Found during:** Task 1 verification
- **Issue:** Existing test in `tests/test_alert_router.py` expected 2 blocks (header + section) for approval request, but the enhanced blocks now produce 4 blocks (header + 2 sections + actions)
- **Fix:** Updated assertion from `len(blocks) == 2` to `len(blocks) == 4` and added action_id verification for approve_trade/reject_trade buttons
- **Files modified:** tests/test_alert_router.py
- **Commit:** 030bdb8

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Approval requests sent via chat.postMessage (not webhook) | Slack webhooks cannot send interactive action_id buttons; chat.postMessage with bot token is required |
| Handler functions as closures capturing approval_manager | slack-bolt @app.action decorator requires registration; closure cleanly captures deps without global state |
| Slack bot started only when bot_token AND app_token AND approval_manager configured | Socket Mode requires both tokens; no point running without approval_manager to resolve against |
| Slack bot task cancelled before alert router in shutdown | Bot should stop accepting interactions before alert routing stops |

## Next Phase Readiness

Plan 08-05 is the final plan in Phase 8 (Alerts & Autonomy). All 5 plans are complete:
- 08-01: Alert routing infrastructure (SlackNotifier, SMSNotifier, AlertRouter)
- 08-02: ApprovalManager with Redis state and timeout-to-reject
- 08-03: Pipeline approval gate with threshold routing
- 08-04: Dashboard approval UI
- 08-05: Slack interactive buttons (this plan)

The complete Alerts & Autonomy phase provides:
- Multi-channel alert routing (Slack + SMS) via Redis pub/sub
- Human-in-the-loop trade approval with configurable auto-execute thresholds
- Three approval resolution interfaces: Slack buttons, dashboard UI, and API
- Safe defaults: timeout-to-reject, non-fatal errors, graceful degradation

---
*Phase: 08-alerts-autonomy*
*Completed: 2026-04-05*
