"""REST endpoints for approval queue management.

Provides GET /api/approvals/pending for listing pending trade approvals
from Redis, and POST /api/approvals/{approval_id}/resolve for approving
or rejecting a pending trade. Both endpoints delegate to ApprovalManager
stored on app.state.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, HTTPException, Request

from trading.dashboard.models import (
    ApprovalContext,
    ApprovalResolveRequest,
    ApprovalResolveResponse,
    ApprovalResponse,
)

logger = structlog.get_logger().bind(component="approvals_routes")

router = APIRouter(prefix="/api", tags=["approvals"])


@router.get("/approvals/pending", response_model=list[ApprovalResponse])
async def get_pending_approvals(request: Request) -> list[ApprovalResponse]:
    """Return all pending approval requests from Redis.

    Retrieves pending approvals from ApprovalManager, parses the
    context JSON string into a structured ApprovalContext, and returns
    the list sorted by requested_at (oldest first).

    Returns:
        List of ApprovalResponse sorted by requested_at ascending.
    """
    approval_manager = getattr(request.app.state, "approval_manager", None)
    if approval_manager is None:
        return []

    try:
        pending = await approval_manager.get_pending()
    except Exception:
        logger.warning("approvals.get_pending_failed", exc_info=True)
        return []

    responses: list[ApprovalResponse] = []
    for item in pending:
        # Parse context from JSON string back into dict
        context_raw = item.get("context", "{}")
        if isinstance(context_raw, str):
            try:
                context_dict = json.loads(context_raw)
            except (json.JSONDecodeError, TypeError):
                context_dict = {}
        else:
            context_dict = context_raw if isinstance(context_raw, dict) else {}

        # Build ApprovalContext if all required fields present, else use dict
        try:
            context = ApprovalContext(**context_dict)
        except Exception:
            context = context_dict

        responses.append(
            ApprovalResponse(
                approval_id=item.get("approval_id", ""),
                status=item.get("status", "pending"),
                context=context,
                requested_at=item.get("requested_at", ""),
                timeout_at=item.get("timeout_at", ""),
                resolved_at=item.get("resolved_at"),
            )
        )

    # Sort by requested_at ascending (oldest first)
    responses.sort(key=lambda r: r.requested_at)

    logger.debug("approvals.list_pending", count=len(responses))
    return responses


@router.post(
    "/approvals/{approval_id}/resolve",
    response_model=ApprovalResolveResponse,
)
async def resolve_approval(
    approval_id: str,
    body: ApprovalResolveRequest,
    request: Request,
) -> ApprovalResolveResponse:
    """Resolve a pending approval by approving or rejecting it.

    Delegates to ApprovalManager.resolve() which updates Redis state,
    publishes the resolution event, and sets the asyncio.Future if
    the approval is being waited on in-process.

    Args:
        approval_id: The unique approval request ID.
        body: Request body with decision ("approved" or "rejected").

    Returns:
        ApprovalResolveResponse with success status and decision.

    Raises:
        HTTPException: 503 if approval manager not available.
    """
    approval_manager = getattr(request.app.state, "approval_manager", None)
    if approval_manager is None:
        raise HTTPException(
            status_code=503, detail="Approval manager not available"
        )

    try:
        result = await approval_manager.resolve(approval_id, body.decision)
    except Exception:
        logger.error(
            "approvals.resolve_failed",
            approval_id=approval_id,
            decision=body.decision,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Failed to resolve approval"
        )

    logger.info(
        "approvals.resolved",
        approval_id=approval_id,
        decision=body.decision,
        success=result,
    )

    return ApprovalResolveResponse(
        success=result,
        approval_id=approval_id,
        decision=body.decision,
    )
