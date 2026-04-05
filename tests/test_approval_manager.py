"""Unit tests for ApprovalManager.

Tests cover: Redis persistence, approve/reject resolution, timeout
auto-reject, invalid decision handling, get_pending filtering, expired
recovery, pub/sub event publishing, and cross-process resolution via
pub/sub listener.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import pytest

from trading.alerts.approval import ApprovalManager


@pytest.fixture
def redis():
    """Create a FakeRedis client for testing."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def manager(redis):
    """Create an ApprovalManager with short timeout for tests."""
    return ApprovalManager(redis=redis, timeout_seconds=2)


# -----------------------------------------------------------------------
# Test 1: request_approval stores state in Redis
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_approval_stores_in_redis(redis, manager):
    """request_approval stores pending state in Redis hash."""
    context = {"symbol": "AAPL", "strategy": "iron_condor", "max_loss": 500}

    async def _request():
        return await manager.request_approval("test-001", context)

    task = asyncio.create_task(_request())

    # Give time for the request to store in Redis
    await asyncio.sleep(0.1)

    # Verify Redis hash exists with correct fields
    data = await redis.hgetall("approval:test-001")
    assert data["status"] == "pending"
    assert json.loads(data["context"]) == context
    assert "requested_at" in data
    assert "timeout_at" in data

    # Resolve so the task can finish
    await manager.resolve("test-001", "approved")
    result = await task
    assert result == "approved"


# -----------------------------------------------------------------------
# Test 2: resolve with "approved" decision
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_approval_approved(redis, manager):
    """resolve with 'approved' returns approved and updates Redis."""
    context = {"symbol": "TSLA"}

    async def _request():
        return await manager.request_approval("test-002", context)

    task = asyncio.create_task(_request())
    await asyncio.sleep(0.1)

    ok = await manager.resolve("test-002", "approved")
    assert ok is True

    result = await task
    assert result == "approved"

    # Verify Redis state updated
    data = await redis.hgetall("approval:test-002")
    assert data["status"] == "approved"
    assert "resolved_at" in data


# -----------------------------------------------------------------------
# Test 3: resolve with "rejected" decision
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_approval_rejected(redis, manager):
    """resolve with 'rejected' returns rejected and updates Redis."""
    context = {"symbol": "MSFT"}

    async def _request():
        return await manager.request_approval("test-003", context)

    task = asyncio.create_task(_request())
    await asyncio.sleep(0.1)

    ok = await manager.resolve("test-003", "rejected")
    assert ok is True

    result = await task
    assert result == "rejected"

    # Verify Redis state updated
    data = await redis.hgetall("approval:test-003")
    assert data["status"] == "rejected"
    assert "resolved_at" in data


# -----------------------------------------------------------------------
# Test 4: timeout auto-rejects
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_auto_rejects(redis):
    """Unanswered approval times out to 'timed_out'."""
    manager = ApprovalManager(redis=redis, timeout_seconds=1)
    context = {"symbol": "SPY"}

    result = await manager.request_approval("test-004", context)
    assert result == "timed_out"

    # Verify Redis state updated
    data = await redis.hgetall("approval:test-004")
    assert data["status"] == "timed_out"
    assert "resolved_at" in data


# -----------------------------------------------------------------------
# Test 5: resolve with invalid decision returns False
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_invalid_decision(redis, manager):
    """resolve with invalid decision returns False."""
    ok = await manager.resolve("test-005", "maybe")
    assert ok is False


# -----------------------------------------------------------------------
# Test 6: get_pending returns only pending approvals
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pending_returns_only_pending(redis, manager):
    """get_pending returns only approvals with status='pending'."""
    # Create two approvals manually in Redis
    await redis.hset(
        "approval:pending-1",
        mapping={"status": "pending", "context": "{}"},
    )
    await redis.hset(
        "approval:resolved-1",
        mapping={"status": "approved", "context": "{}"},
    )

    pending = await manager.get_pending()
    assert len(pending) == 1
    assert pending[0]["approval_id"] == "pending-1"
    assert pending[0]["status"] == "pending"


# -----------------------------------------------------------------------
# Test 7: recover_expired auto-rejects expired approvals
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_expired_auto_rejects(redis, manager):
    """recover_expired auto-rejects approvals past their timeout."""
    # Manually write an expired approval
    past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    await redis.hset(
        "approval:expired-1",
        mapping={
            "status": "pending",
            "context": "{}",
            "requested_at": past,
            "timeout_at": past,
        },
    )

    count = await manager.recover_expired()
    assert count == 1

    # Verify status updated
    data = await redis.hgetall("approval:expired-1")
    assert data["status"] == "timed_out"
    assert "resolved_at" in data


# -----------------------------------------------------------------------
# Test 8: recover_expired skips active (non-expired) approvals
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_expired_skips_active(redis, manager):
    """recover_expired skips pending approvals not yet expired."""
    future_time = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).isoformat()
    await redis.hset(
        "approval:active-1",
        mapping={
            "status": "pending",
            "context": "{}",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "timeout_at": future_time,
        },
    )

    count = await manager.recover_expired()
    assert count == 0

    # Verify status still pending
    data = await redis.hgetall("approval:active-1")
    assert data["status"] == "pending"


# -----------------------------------------------------------------------
# Test 9: publish events on request and resolve
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_events(redis, manager):
    """request_approval publishes to alerts:approval_request and
    resolve publishes to alerts:approval_resolved."""
    # Subscribe to both channels to capture messages
    pubsub = redis.pubsub()
    await pubsub.subscribe(
        "alerts:approval_request", "alerts:approval_resolved"
    )

    # Drain subscription confirmations
    for _ in range(2):
        msg = await pubsub.get_message(timeout=1)

    context = {"symbol": "GOOG"}

    async def _request():
        return await manager.request_approval("test-pub", context)

    task = asyncio.create_task(_request())
    await asyncio.sleep(0.1)

    # Read the approval_request event
    msg = await pubsub.get_message(timeout=1)
    assert msg is not None
    assert msg["channel"] == "alerts:approval_request"
    data = json.loads(msg["data"])
    assert data["approval_id"] == "test-pub"
    assert data["symbol"] == "GOOG"

    # Resolve and read the approval_resolved event
    await manager.resolve("test-pub", "approved")
    await task

    # There may be two resolved messages (one from resolve, one from
    # _resolve_internal called by the resolve path). Read available.
    resolved_msgs = []
    for _ in range(5):
        msg = await pubsub.get_message(timeout=0.5)
        if msg and msg["type"] == "message":
            resolved_msgs.append(msg)

    # At least one resolved message should exist
    resolved_channels = [m["channel"] for m in resolved_msgs]
    assert "alerts:approval_resolved" in resolved_channels

    resolved_data = json.loads(
        next(
            m["data"]
            for m in resolved_msgs
            if m["channel"] == "alerts:approval_resolved"
        )
    )
    assert resolved_data["approval_id"] == "test-pub"
    assert resolved_data["decision"] == "approved"

    await pubsub.unsubscribe()
    await pubsub.aclose()


# -----------------------------------------------------------------------
# Test 10: cross-process resolution via pub/sub
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_process_resolution_via_pubsub(redis):
    """Simulated cross-process resolution via Redis pub/sub wakes
    the waiting Future without calling resolve() directly."""
    manager = ApprovalManager(redis=redis, timeout_seconds=5)
    context = {"symbol": "AMZN", "strategy": "put_spread"}

    async def _request():
        return await manager.request_approval("cross-001", context)

    task = asyncio.create_task(_request())

    # Wait for the request to be stored and listener to be active
    await asyncio.sleep(0.2)

    # Simulate cross-process resolution: publish directly to Redis
    # (NOT calling manager.resolve -- simulating another process)
    await redis.publish(
        "alerts:approval_resolved",
        json.dumps({"approval_id": "cross-001", "decision": "rejected"}),
    )

    # The pub/sub listener should pick this up and set the future
    result = await asyncio.wait_for(task, timeout=3)
    assert result == "rejected"
