---
phase: 08-alerts-autonomy
plan: 01
subsystem: alerts
tags: [slack, sms, twilio, redis-pubsub, alerts, notifications]

dependency_graph:
  requires: []
  provides:
    - AlertConfig and AutoExecuteConfig Pydantic models
    - SlackNotifier with Block Kit formatting via AsyncWebhookClient
    - SMSNotifier with Twilio REST API via httpx and per-channel cooldown
    - AlertRouter consuming Redis pub/sub and fanning out to notifiers
  affects:
    - 08-02 (event publishing hooks use alert channels)
    - 08-03 (approval workflow uses AutoExecuteConfig thresholds)
    - 08-04 (dashboard approval UI consumes approval events)
    - 08-05 (Slack interactive buttons extend SlackNotifier)

tech_stack:
  added:
    - slack-bolt>=1.27.0
    - slack-sdk>=3.41.0
    - httpx>=0.28.1
    - aiohttp>=3.9.0
  patterns:
    - Redis pub/sub subscription with exact channels (not patterns) for alert routing
    - Per-channel cooldown tracking via monotonic timestamps for SMS rate limiting
    - Block Kit dict structures for Slack message formatting
    - Non-fatal notifier errors with independent try/except per notifier

file_tracking:
  created:
    - src/trading/alerts/__init__.py
    - src/trading/alerts/config.py
    - src/trading/alerts/slack.py
    - src/trading/alerts/sms.py
    - src/trading/alerts/router.py
    - tests/test_alert_router.py
  modified:
    - pyproject.toml
    - config/default.yml
    - src/trading/config.py

decisions:
  - id: 08-01-aiohttp
    description: Added aiohttp as explicit dependency (required by slack-sdk AsyncWebhookClient at import time)
    rationale: Plan said not to add explicitly, but slack-sdk fails to import without it and slack-bolt does not install it transitively without [async] extra

metrics:
  duration: 5min
  completed: 2026-04-05
  tests_passed: 20
  tests_total: 20
---

# Phase 8 Plan 1: Alert Routing Infrastructure Summary

**One-liner:** Redis pub/sub alert router with Slack Block Kit webhook notifications, Twilio SMS via httpx with per-channel cooldown, and paper/live auto-execute threshold config.

## What Was Built

### Alert Config Models (`src/trading/alerts/config.py` - 95 lines)
- `AutoExecuteThresholds`: max_loss_dollars, max_delta_impact, max_vega_impact, approval_timeout_seconds with validation
- `AutoExecuteConfig`: Paper/live threshold separation (paper 2x live, matching risk_limits pattern)
- `AlertConfig`: Slack webhook/bot/app tokens, SMS Twilio credentials, channel filtering, cooldown settings
- All wired into `Settings` class and loaded from `config/default.yml`

### Slack Notifier (`src/trading/alerts/slack.py` - 275 lines)
- `SlackNotifier` sends formatted messages via `AsyncWebhookClient`
- `_build_blocks()` generates Block Kit structures for 6 known channel types:
  - `alerts:trade_executed` - green header with symbol, strategy, fill price, quantity
  - `alerts:risk_breach` - header with breach reason and details
  - `alerts:circuit_breaker` - header with halt reason
  - `alerts:system_error` - header with error message and component
  - `alerts:approval_request` - header with trade context fields
  - `alerts:approval_resolved` - header with decision result
- Unknown channels get generic section block with JSON summary
- All sends wrapped in try/except (non-fatal)

### SMS Notifier (`src/trading/alerts/sms.py` - 139 lines)
- `SMSNotifier` sends SMS via httpx POST to Twilio REST API
- Per-channel cooldown via `_last_sent` dict with monotonic timestamps
- Message body truncated to 160 chars (single SMS segment)
- Failed sends do not update cooldown (allows retry on next event)
- All sends wrapped in try/except (non-fatal)

### Alert Router (`src/trading/alerts/router.py` - 141 lines)
- `AlertRouter` subscribes to 7 Redis pub/sub channels (exact, not pattern)
- Routes to Slack for all channels (when enabled)
- Routes to SMS only for high-severity channels in `sms_channels` list
- Each notifier called independently with own try/except
- Clean shutdown on `asyncio.CancelledError` (unsubscribe + close)
- Handles None notifiers gracefully (no crash if unconfigured)

### Unit Tests (`tests/test_alert_router.py` - 460 lines, 20 tests)
- Routing: Slack called for all channels, SMS only for sms_channels
- Disable: Slack/SMS skipped when disabled
- Error isolation: Slack error doesn't block SMS and vice versa
- None handling: Router works with None notifiers
- Channel coverage: All 7 expected event types present
- Cooldown: Second SMS within window skipped; different channels independent; error doesn't update cooldown
- Block Kit: All 6 known channels produce header blocks; unknown gets generic section
- SMS body: Truncated to 160 chars

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added aiohttp as explicit dependency**
- **Found during:** Task 2 import verification
- **Issue:** `slack_sdk.webhook.async_client.AsyncWebhookClient` imports `aiohttp` at module level. The plan noted aiohttp comes transitively from slack-bolt[async], but `slack-bolt` (without [async] extra) was installed, which does not pull aiohttp.
- **Fix:** Added `aiohttp>=3.9.0` to pyproject.toml dependencies
- **Files modified:** pyproject.toml
- **Commit:** 828790a

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Added aiohttp explicitly | slack-sdk AsyncWebhookClient requires it at import time; slack-bolt without [async] extra doesn't install it |
| Exact channel subscribe (not psubscribe) | AlertRouter uses `subscribe()` not `psubscribe()` for precise channel matching, unlike RedisBridge which uses patterns for wildcard market data channels |
| Monotonic timestamps for cooldown | `time.monotonic()` is immune to system clock adjustments, correct for interval measurement |
| Independent try/except per notifier | One notifier failure must not block the other -- each wrapped individually in _route() |

## Next Phase Readiness

All deliverables for 08-01 are complete. The alert routing infrastructure is ready for:
- **08-02:** Event publishing hooks can publish to `alerts:*` channels consumed by AlertRouter
- **08-03:** Approval workflow can use `AutoExecuteConfig` thresholds for gate decisions
- **08-05:** Slack interactive buttons can extend the `SlackNotifier` with Socket Mode handler

No blockers or concerns for downstream plans.
