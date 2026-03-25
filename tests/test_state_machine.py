"""Unit tests for order lifecycle state machine and tracker.

Tests cover:
- Happy path transitions (market order, limit with pre-submit)
- Cancel and reject flows
- Invalid transitions and final state enforcement
- IB status string mapping
- Database persistence via mocked sessions
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from statemachine.exceptions import TransitionNotAllowed

from trading.orders.state_machine import OrderStateMachine
from trading.orders.tracker import IB_STATUS_TO_EVENT, OrderTracker


# ---------------------------------------------------------------------------
# State machine transition tests
# ---------------------------------------------------------------------------


class TestOrderStateMachineTransitions:
    """Tests for valid and invalid state machine transitions."""

    def test_initial_state_is_created(self):
        """New machine starts in 'created' state."""
        sm = OrderStateMachine()
        assert sm.current_state_value == "CREATED"

    def test_happy_path_market_order(self):
        """Market order: created -> api_pending -> pending_submit -> submitted -> filled."""
        sm = OrderStateMachine(order_id="order-1")
        sm.submit()
        assert sm.current_state_value == "API_PENDING"
        sm.sent()
        assert sm.current_state_value == "PENDING_SUBMIT"
        sm.accept()
        assert sm.current_state_value == "SUBMITTED"
        sm.fill()
        assert sm.current_state_value == "FILLED"

    def test_happy_path_with_pre_submit(self):
        """Limit order: created -> ... -> pre_submitted -> submitted -> filled."""
        sm = OrderStateMachine(order_id="order-2")
        sm.submit()
        sm.sent()
        sm.pre_submit()
        assert sm.current_state_value == "PRE_SUBMITTED"
        sm.accept()
        assert sm.current_state_value == "SUBMITTED"
        sm.fill()
        assert sm.current_state_value == "FILLED"

    def test_cancel_flow(self):
        """Cancel flow: submitted -> pending_cancel -> cancelled."""
        sm = OrderStateMachine()
        sm.submit()
        sm.sent()
        sm.accept()
        sm.request_cancel()
        assert sm.current_state_value == "PENDING_CANCEL"
        sm.cancel()
        assert sm.current_state_value == "CANCELLED"

    def test_api_cancel(self):
        """API cancel: api_pending -> cancelled."""
        sm = OrderStateMachine()
        sm.submit()
        assert sm.current_state_value == "API_PENDING"
        sm.api_cancel()
        assert sm.current_state_value == "CANCELLED"

    def test_reject_flow(self):
        """Reject flow: pending_submit -> error."""
        sm = OrderStateMachine()
        sm.submit()
        sm.sent()
        sm.reject()
        assert sm.current_state_value == "ERROR"

    def test_invalid_transition_raises(self):
        """Cannot fill from created state."""
        sm = OrderStateMachine()
        with pytest.raises(TransitionNotAllowed):
            sm.fill()

    def test_cannot_transition_from_final_state(self):
        """No transitions allowed from filled (final) state."""
        sm = OrderStateMachine()
        sm.submit()
        sm.sent()
        sm.accept()
        sm.fill()
        assert sm.current_state_value == "FILLED"

        with pytest.raises(TransitionNotAllowed):
            sm.submit()

        with pytest.raises(TransitionNotAllowed):
            sm.cancel()

    def test_partial_fill_self_transition(self):
        """Partial fill keeps machine in submitted state."""
        sm = OrderStateMachine()
        sm.submit()
        sm.sent()
        sm.accept()
        assert sm.current_state_value == "SUBMITTED"
        sm.partial_fill()
        assert sm.current_state_value == "SUBMITTED"
        # Can still fill after partial
        sm.fill()
        assert sm.current_state_value == "FILLED"

    def test_cancel_from_pre_submitted(self):
        """Can request cancel from pre_submitted state."""
        sm = OrderStateMachine()
        sm.submit()
        sm.sent()
        sm.pre_submit()
        sm.request_cancel()
        assert sm.current_state_value == "PENDING_CANCEL"

    def test_fill_from_pre_submitted(self):
        """Can fill directly from pre_submitted (e.g., limit order fills immediately)."""
        sm = OrderStateMachine()
        sm.submit()
        sm.sent()
        sm.pre_submit()
        sm.fill()
        assert sm.current_state_value == "FILLED"

    def test_reject_from_api_pending(self):
        """Reject from api_pending (IB rejects before reaching exchange)."""
        sm = OrderStateMachine()
        sm.submit()
        sm.reject()
        assert sm.current_state_value == "ERROR"

    def test_cancel_from_submitted_directly(self):
        """Can cancel directly from submitted without pending_cancel."""
        sm = OrderStateMachine()
        sm.submit()
        sm.sent()
        sm.accept()
        sm.cancel()
        assert sm.current_state_value == "CANCELLED"

    def test_order_id_is_stored(self):
        """Machine stores the order_id for identification."""
        sm = OrderStateMachine(order_id="abc-123")
        assert sm.order_id == "abc-123"


# ---------------------------------------------------------------------------
# Transition recording tests
# ---------------------------------------------------------------------------


class TestTransitionRecording:
    """Tests for on_enter_state callback and transition consumption."""

    def test_transitions_are_recorded(self):
        """Each transition is recorded with from/to/event."""
        sm = OrderStateMachine(order_id="rec-1")
        sm.submit()
        transitions = sm.consume_transitions()
        assert len(transitions) == 1
        assert transitions[0]["from_state"] == "CREATED"
        assert transitions[0]["to_state"] == "API_PENDING"
        assert transitions[0]["event"] == "submit"

    def test_consume_clears_pending(self):
        """consume_transitions clears the pending list."""
        sm = OrderStateMachine()
        sm.submit()
        sm.consume_transitions()
        assert len(sm.consume_transitions()) == 0

    def test_multiple_transitions_recorded(self):
        """Multiple transitions accumulate before consumption."""
        sm = OrderStateMachine()
        sm.submit()
        sm.sent()
        sm.accept()
        transitions = sm.consume_transitions()
        assert len(transitions) == 3
        assert transitions[0]["event"] == "submit"
        assert transitions[1]["event"] == "sent"
        assert transitions[2]["event"] == "accept"

    def test_initial_event_not_recorded(self):
        """The __initial__ pseudo-event is not captured."""
        sm = OrderStateMachine()
        assert len(sm._pending_transitions) == 0


# ---------------------------------------------------------------------------
# IB status mapping tests
# ---------------------------------------------------------------------------


class TestIBStatusMapping:
    """Tests for IB status string to event mapping via OrderTracker."""

    @pytest.fixture()
    def tracker(self):
        """Create a tracker with a mock session factory."""
        session_factory = AsyncMock()
        return OrderTracker(session_factory)

    async def test_ib_status_submitted_maps_to_accept(self, tracker):
        """IB 'Submitted' status maps to 'accept' event."""
        tracker.create_order("o1")
        m = tracker.get_machine("o1")
        m.submit()
        m.sent()
        m.consume_transitions()  # Clear pending

        with patch.object(tracker, "persist_transition", new_callable=AsyncMock):
            result = await tracker.handle_ib_status("o1", "Submitted")
        assert result == "SUBMITTED"

    async def test_ib_status_filled_maps_to_fill(self, tracker):
        """IB 'Filled' status maps to 'fill' event."""
        tracker.create_order("o2")
        m = tracker.get_machine("o2")
        m.submit()
        m.sent()
        m.accept()
        m.consume_transitions()

        with patch.object(tracker, "persist_transition", new_callable=AsyncMock):
            result = await tracker.handle_ib_status("o2", "Filled")
        assert result == "FILLED"

    async def test_ib_status_inactive_maps_to_reject(self, tracker):
        """IB 'Inactive' status maps to 'reject' event."""
        tracker.create_order("o3")
        m = tracker.get_machine("o3")
        m.submit()
        m.consume_transitions()

        with patch.object(tracker, "persist_transition", new_callable=AsyncMock):
            result = await tracker.handle_ib_status("o3", "Inactive")
        assert result == "ERROR"

    async def test_ib_status_cancelled(self, tracker):
        """IB 'Cancelled' status maps to 'cancel' event."""
        tracker.create_order("o4")
        m = tracker.get_machine("o4")
        m.submit()
        m.sent()
        m.accept()
        m.request_cancel()
        m.consume_transitions()

        with patch.object(tracker, "persist_transition", new_callable=AsyncMock):
            result = await tracker.handle_ib_status("o4", "Cancelled")
        assert result == "CANCELLED"

    async def test_ib_status_api_cancelled(self, tracker):
        """IB 'ApiCancelled' status maps to 'api_cancel' event."""
        tracker.create_order("o5")
        m = tracker.get_machine("o5")
        m.submit()
        m.consume_transitions()

        with patch.object(tracker, "persist_transition", new_callable=AsyncMock):
            result = await tracker.handle_ib_status("o5", "ApiCancelled")
        assert result == "CANCELLED"

    async def test_ib_status_pre_submitted(self, tracker):
        """IB 'PreSubmitted' status maps to 'pre_submit' event."""
        tracker.create_order("o6")
        m = tracker.get_machine("o6")
        m.submit()
        m.sent()
        m.consume_transitions()

        with patch.object(tracker, "persist_transition", new_callable=AsyncMock):
            result = await tracker.handle_ib_status("o6", "PreSubmitted")
        assert result == "PRE_SUBMITTED"

    async def test_ib_status_unknown_raises(self, tracker):
        """Unknown IB status raises ValueError."""
        tracker.create_order("o7")
        with pytest.raises(ValueError, match="Unknown IB status"):
            await tracker.handle_ib_status("o7", "SomeRandomStatus")

    async def test_ib_status_invalid_transition_returns_current(self, tracker):
        """Invalid IB transition logs warning and returns current state."""
        tracker.create_order("o8")
        # Machine is in 'created', 'Filled' maps to 'fill' which is invalid
        with patch.object(tracker, "persist_transition", new_callable=AsyncMock):
            result = await tracker.handle_ib_status("o8", "Filled")
        assert result == "CREATED"

    def test_all_ib_statuses_mapped(self):
        """All expected IB statuses are covered in the mapping."""
        expected = {
            "ApiPending",
            "PendingSubmit",
            "PreSubmitted",
            "Submitted",
            "Filled",
            "Cancelled",
            "ApiCancelled",
            "Inactive",
        }
        assert set(IB_STATUS_TO_EVENT.keys()) == expected


# ---------------------------------------------------------------------------
# Tracker core functionality tests
# ---------------------------------------------------------------------------


class TestOrderTracker:
    """Tests for OrderTracker create/get/transition methods."""

    @pytest.fixture()
    def tracker(self):
        """Create a tracker with a mock session factory."""
        session_factory = AsyncMock()
        return OrderTracker(session_factory)

    def test_create_order(self, tracker):
        """create_order returns a new state machine and stores it."""
        sm = tracker.create_order("new-1")
        assert isinstance(sm, OrderStateMachine)
        assert sm.order_id == "new-1"
        assert tracker.get_machine("new-1") is sm

    def test_create_duplicate_raises(self, tracker):
        """Creating an order with duplicate ID raises ValueError."""
        tracker.create_order("dup-1")
        with pytest.raises(ValueError, match="already tracked"):
            tracker.create_order("dup-1")

    def test_get_machine_unknown_returns_none(self, tracker):
        """get_machine returns None for unknown order IDs."""
        assert tracker.get_machine("nonexistent") is None

    async def test_transition_unknown_order_raises(self, tracker):
        """Transition on unknown order raises KeyError."""
        with pytest.raises(KeyError, match="not tracked"):
            await tracker.transition("unknown-id", "submit")

    async def test_transition_invalid_raises(self, tracker):
        """Invalid transition re-raises TransitionNotAllowed."""
        tracker.create_order("inv-1")
        with pytest.raises(TransitionNotAllowed):
            await tracker.transition("inv-1", "fill")


# ---------------------------------------------------------------------------
# Tracker persistence tests (mocked DB)
# ---------------------------------------------------------------------------


class TestTrackerPersistence:
    """Tests for database persistence of state transitions."""

    @pytest.fixture()
    def mock_session(self):
        """Create a mock async session with execute support."""
        session = AsyncMock()
        # Mock execute().scalar_one_or_none() to return an order-like object
        mock_order = MagicMock()
        mock_order.current_state = "CREATED"
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_order
        session.execute = AsyncMock(return_value=result)
        return session, mock_order

    @pytest.fixture()
    def tracker_with_mock_db(self, mock_session):
        """Create a tracker with a mocked session factory."""
        session, mock_order = mock_session

        # Create a mock async context manager for get_session
        session_factory = AsyncMock()

        tracker = OrderTracker(session_factory)
        return tracker, session, mock_order

    async def test_transition_persists_to_db(self, tracker_with_mock_db):
        """Transition creates an OrderStateTransition record in the database."""
        tracker, session, mock_order = tracker_with_mock_db

        tracker.create_order("persist-1")

        with patch("trading.orders.tracker.get_session") as mock_get_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = mock_ctx

            await tracker.transition("persist-1", "submit")

        # Verify session.add was called with a transition record
        session.add.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert added_obj.order_id == "persist-1"
        assert added_obj.from_state == "CREATED"
        assert added_obj.to_state == "API_PENDING"
        assert added_obj.event == "submit"

    async def test_transition_updates_order_state(self, tracker_with_mock_db):
        """Transition updates Order.current_state to the new state."""
        tracker, session, mock_order = tracker_with_mock_db

        tracker.create_order("update-1")

        with patch("trading.orders.tracker.get_session") as mock_get_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = mock_ctx

            await tracker.transition("update-1", "submit")

        # Verify the order's current_state was updated
        assert mock_order.current_state == "API_PENDING"

    async def test_transition_with_details_persisted(self, tracker_with_mock_db):
        """Details string is stored in the transition record."""
        tracker, session, mock_order = tracker_with_mock_db

        tracker.create_order("detail-1")

        with patch("trading.orders.tracker.get_session") as mock_get_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = mock_ctx

            await tracker.transition(
                "detail-1", "submit", details="User initiated"
            )

        added_obj = session.add.call_args[0][0]
        assert added_obj.details == "User initiated"
