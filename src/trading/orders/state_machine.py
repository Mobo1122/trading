"""Order lifecycle state machine using python-statemachine.

Defines the deterministic state machine that governs all valid
order state transitions, mirroring the IB Gateway order lifecycle.
Invalid transitions are rejected with TransitionNotAllowed.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from trading.db.models import OrderState


class OrderStateMachine(StateMachine):
    """Deterministic state machine for order lifecycle management.

    States match the OrderState enum from db/models.py. Transitions
    model every valid IB order status change, including pre-submitted,
    pending-cancel, partial fills, and API-level cancellations.

    Attributes:
        order_id: The UUID of the order this machine tracks.
    """

    # --- States (matching OrderState enum) ---
    created = State(initial=True, value=OrderState.CREATED.value)
    api_pending = State(value=OrderState.API_PENDING.value)
    pending_submit = State(value=OrderState.PENDING_SUBMIT.value)
    pre_submitted = State(value=OrderState.PRE_SUBMITTED.value)
    submitted = State(value=OrderState.SUBMITTED.value)
    pending_cancel = State(value=OrderState.PENDING_CANCEL.value)
    filled = State(final=True, value=OrderState.FILLED.value)
    cancelled = State(final=True, value=OrderState.CANCELLED.value)
    error = State(final=True, value=OrderState.ERROR.value)

    # --- Transitions ---

    # Order submission flow
    submit = created.to(api_pending)
    sent = api_pending.to(pending_submit)
    pre_submit = pending_submit.to(pre_submitted)
    accept = pending_submit.to(submitted) | pre_submitted.to(submitted)

    # Cancel flow
    request_cancel = (
        pending_submit.to(pending_cancel)
        | pre_submitted.to(pending_cancel)
        | submitted.to(pending_cancel)
    )
    cancel = pending_cancel.to(cancelled) | submitted.to(cancelled)
    api_cancel = pending_cancel.to(cancelled) | api_pending.to(cancelled)

    # Fill flow
    fill = submitted.to(filled) | pre_submitted.to(filled)
    partial_fill = submitted.to.itself()

    # Error flow
    reject = (
        api_pending.to(error)
        | pending_submit.to(error)
        | pre_submitted.to(error)
        | submitted.to(error)
    )

    def __init__(self, order_id: str = "") -> None:
        """Initialize the state machine for a specific order.

        Args:
            order_id: The UUID of the order this machine tracks.
        """
        self.order_id = order_id
        self._pending_transitions: list[dict[str, str | None]] = []
        super().__init__()

    def on_enter_state(self, source: State, target: State, event: str) -> None:
        """Record every state transition for the tracker to consume.

        Stores transition details (source, target, event) in a pending
        list that the OrderTracker reads and persists to the database.

        Args:
            source: The state being exited.
            target: The state being entered.
            event: The name of the event triggering this transition.
        """
        # Skip the initial __initial__ pseudo-event
        event_name = str(event)
        if event_name == "__initial__":
            return

        self._pending_transitions.append(
            {
                "from_state": source.value if source else None,
                "to_state": target.value,
                "event": event_name,
            }
        )

    def consume_transitions(self) -> list[dict[str, str | None]]:
        """Return and clear all pending transition records.

        Called by OrderTracker after sending an event to collect
        transition details for database persistence.

        Returns:
            List of transition dicts with from_state, to_state, event keys.
        """
        transitions = list(self._pending_transitions)
        self._pending_transitions.clear()
        return transitions
