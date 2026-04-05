"""Approval manager for human-in-the-loop trade approval workflow.

Manages pending trade approvals with Redis persistence, asyncio.Future-based
timeout-to-reject, cross-process resolution via Redis pub/sub, and startup
recovery of expired approvals.

The ApprovalManager is the core state machine used by:
  - Pipeline approval gate (routes trades needing human approval)
  - Dashboard approval UI (REST endpoint resolves approvals)
  - Slack interactive buttons (Socket Mode handler resolves approvals)

Approval lifecycle::

    request_approval() -> Redis hash "pending" -> publish alerts:approval_request
                       -> wait Future (with pub/sub listener for cross-process)
                       -> resolve() or timeout
                       -> Redis hash updated -> publish alerts:approval_resolved
                       -> return "approved" | "rejected" | "timed_out"

Terminal states: "approved", "rejected", "timed_out".
Safe default: unanswered approvals time out to "timed_out" (reject).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

log = structlog.get_logger(component="approval_manager")


class ApprovalManager:
    """Manages pending trade approvals with timeout-to-reject.

    Stores approval state in Redis hashes (``approval:{id}``), waits for
    resolution via an ``asyncio.Future`` with configurable timeout, and
    publishes events to Redis pub/sub for alert routing.

    Cross-process resolution: ``request_approval`` spawns a background task
    that listens on ``alerts:approval_resolved`` via Redis pub/sub. When a
    matching resolution arrives from another process (dashboard, Slack bot),
    it sets the Future result and unblocks the waiting coroutine.

    Args:
        redis: Async Redis client (``decode_responses=True``).
        timeout_seconds: Seconds to wait before auto-rejecting (default 300).
    """

    def __init__(self, redis: Any, timeout_seconds: int = 300) -> None:
        self._redis = redis
        self._timeout = timeout_seconds
        self._pending: dict[str, asyncio.Future[str]] = {}

    async def request_approval(self, approval_id: str, context: dict) -> str:
        """Create an approval request and wait for resolution or timeout.

        Stores approval state in Redis, publishes an alert, creates an
        asyncio.Future, and waits up to ``timeout_seconds`` for resolution.
        Resolution can come from an in-process ``resolve()`` call or from
        a cross-process Redis pub/sub message.

        Args:
            approval_id: Unique identifier for this approval request.
            context: Trade context dict (symbol, strategy, max_loss, etc.).

        Returns:
            ``"approved"``, ``"rejected"``, or ``"timed_out"``.
        """
        now = datetime.now(timezone.utc)
        timeout_at = now + timedelta(seconds=self._timeout)

        # Store approval state in Redis hash
        await self._redis.hset(
            f"approval:{approval_id}",
            mapping={
                "status": "pending",
                "context": json.dumps(context),
                "requested_at": now.isoformat(),
                "timeout_at": timeout_at.isoformat(),
            },
        )

        # Keep key for 1 hour after timeout for dashboard visibility
        await self._redis.expire(
            f"approval:{approval_id}", self._timeout + 3600
        )

        # Publish for alert routing (Slack, SMS, dashboard)
        await self._redis.publish(
            "alerts:approval_request",
            json.dumps({"approval_id": approval_id, **context}),
        )

        log.info(
            "approval.requested",
            approval_id=approval_id,
            timeout_seconds=self._timeout,
        )

        # Create Future and register in pending dict
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[approval_id] = future

        # Background listener for cross-process resolution via pub/sub
        async def _listen_for_resolution() -> None:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe("alerts:approval_resolved")
            try:
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if (
                        data.get("approval_id") == approval_id
                        and not future.done()
                    ):
                        future.set_result(data["decision"])
                        break
            finally:
                await pubsub.unsubscribe("alerts:approval_resolved")
                await pubsub.aclose()

        listener_task = asyncio.create_task(_listen_for_resolution())

        try:
            done, _pending = await asyncio.wait(
                {future}, timeout=self._timeout
            )
            if future in done:
                result = future.result()
                log.info(
                    "approval.resolved",
                    approval_id=approval_id,
                    decision=result,
                )
                return result
            else:
                # Timeout -- auto-reject (safe default)
                await self._resolve_internal(approval_id, "timed_out")
                log.warning(
                    "approval.timed_out",
                    approval_id=approval_id,
                    timeout_seconds=self._timeout,
                )
                return "timed_out"
        finally:
            self._pending.pop(approval_id, None)
            if not listener_task.done():
                listener_task.cancel()
                try:
                    await listener_task
                except asyncio.CancelledError:
                    pass

    async def resolve(self, approval_id: str, decision: str) -> bool:
        """Resolve a pending approval from any source.

        Called by the dashboard REST endpoint, Slack interactive button
        handler, or any other resolution source. Updates Redis state and
        publishes the resolution event. If the approval is being waited
        on in this process, sets the Future result directly.

        Args:
            approval_id: The approval request ID.
            decision: ``"approved"`` or ``"rejected"``.

        Returns:
            True if resolved successfully, False if invalid decision.
        """
        if decision not in ("approved", "rejected"):
            log.warning(
                "approval.resolve.invalid_decision",
                approval_id=approval_id,
                decision=decision,
            )
            return False

        # Set Future result if waiting in this process
        future = self._pending.get(approval_id)
        if future is not None and not future.done():
            future.set_result(decision)

        await self._resolve_internal(approval_id, decision)
        return True

    async def _resolve_internal(
        self, approval_id: str, decision: str
    ) -> None:
        """Update Redis state and publish resolution event.

        Args:
            approval_id: The approval request ID.
            decision: Terminal state (``"approved"``, ``"rejected"``,
                or ``"timed_out"``).
        """
        await self._redis.hset(
            f"approval:{approval_id}",
            mapping={
                "status": decision,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        await self._redis.publish(
            "alerts:approval_resolved",
            json.dumps({"approval_id": approval_id, "decision": decision}),
        )

        self._pending.pop(approval_id, None)

    async def get_pending(self) -> list[dict]:
        """Return all pending approval requests from Redis.

        Scans for ``approval:*`` keys and returns those with
        ``status == "pending"``.

        Returns:
            List of dicts with ``approval_id`` and all hash fields.
        """
        pending: list[dict] = []
        async for key in self._redis.scan_iter(match="approval:*"):
            data = await self._redis.hgetall(key)
            if data.get("status") == "pending":
                # Extract approval_id from key name
                approval_id = key.removeprefix("approval:")
                pending.append({"approval_id": approval_id, **data})
        return pending

    async def recover_expired(self) -> int:
        """Recover expired pending approvals from a previous process.

        Called on startup to clean up stale approvals. Scans Redis for
        pending approvals whose ``timeout_at`` has passed and auto-rejects
        them with ``"timed_out"`` status.

        Returns:
            Count of expired approvals that were auto-rejected.
        """
        pending = await self.get_pending()
        now = datetime.now(timezone.utc)
        count = 0

        for approval in pending:
            timeout_at_str = approval.get("timeout_at", "")
            if not timeout_at_str:
                continue

            try:
                timeout_at = datetime.fromisoformat(timeout_at_str)
            except ValueError:
                log.warning(
                    "approval.recover.invalid_timeout",
                    approval_id=approval["approval_id"],
                    timeout_at=timeout_at_str,
                )
                continue

            if now > timeout_at:
                await self._resolve_internal(
                    approval["approval_id"], "timed_out"
                )
                log.info(
                    "approval.recover.expired",
                    approval_id=approval["approval_id"],
                    timeout_at=timeout_at_str,
                )
                count += 1

        if count > 0:
            log.info("approval.recover.complete", expired_count=count)

        return count
