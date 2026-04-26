"""Tests for the market hours helpers used by the scheduler."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from trading.scheduler.market_hours import (
    NY_TZ,
    is_market_open,
    next_market_open,
)


UTC = ZoneInfo("UTC")


def _at(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build a NY-zoned datetime for terse test data."""
    return datetime(year, month, day, hour, minute, tzinfo=NY_TZ)


class TestIsMarketOpen:
    def test_open_during_regular_session(self) -> None:
        # Wednesday 11:00 ET — clearly inside the regular session.
        assert is_market_open(_at(2026, 4, 22, 11, 0)) is True

    def test_open_just_after_open(self) -> None:
        # 9:30 sharp — first second of the session is open.
        assert is_market_open(_at(2026, 4, 22, 9, 30)) is True

    def test_closed_before_open(self) -> None:
        # 9:29 ET — one minute before the bell.
        assert is_market_open(_at(2026, 4, 22, 9, 29)) is False

    def test_closed_at_close(self) -> None:
        # 16:00 ET sharp — the close itself is treated as closed.
        assert is_market_open(_at(2026, 4, 22, 16, 0)) is False

    def test_closed_on_saturday(self) -> None:
        # 2026-04-25 is a Saturday.
        assert is_market_open(_at(2026, 4, 25, 11, 0)) is False

    def test_closed_on_sunday(self) -> None:
        assert is_market_open(_at(2026, 4, 26, 11, 0)) is False

    def test_closed_on_full_holiday(self) -> None:
        # Independence Day observed 2026-07-03.
        assert is_market_open(_at(2026, 7, 3, 11, 0)) is False

    def test_early_close_before_1pm(self) -> None:
        # Day after Thanksgiving 2026-11-27 closes early at 13:00.
        assert is_market_open(_at(2026, 11, 27, 12, 30)) is True

    def test_early_close_after_1pm(self) -> None:
        # Same day at 13:30 — already closed.
        assert is_market_open(_at(2026, 11, 27, 13, 30)) is False

    def test_accepts_utc_input(self) -> None:
        # 15:00 UTC on Wednesday April 22 == 11:00 NY EDT — open.
        utc_now = datetime(2026, 4, 22, 15, 0, tzinfo=UTC)
        assert is_market_open(utc_now) is True


class TestNextMarketOpen:
    def test_next_open_from_weekend(self) -> None:
        # Saturday afternoon → next open is Monday 09:30.
        sat = _at(2026, 4, 25, 14, 0)
        nxt = next_market_open(sat)
        assert nxt.weekday() == 0  # Monday
        assert nxt.hour == 9 and nxt.minute == 30

    def test_next_open_from_post_close(self) -> None:
        # Wednesday 16:30 → next open is Thursday 09:30.
        wed = _at(2026, 4, 22, 16, 30)
        nxt = next_market_open(wed)
        assert nxt.date().day == 23
        assert nxt.hour == 9 and nxt.minute == 30

    def test_next_open_skips_holiday(self) -> None:
        # Day before Independence Day observed (2026-07-02 16:30) →
        # 2026-07-03 is a holiday; next open is Monday 2026-07-06.
        before_holiday = _at(2026, 7, 2, 16, 30)
        nxt = next_market_open(before_holiday)
        assert nxt.date().day == 6
        assert nxt.date().month == 7

    def test_next_open_during_session_returns_tomorrow(self) -> None:
        # During the session itself, "next open" is tomorrow's open
        # (this function doesn't return "now" — it always advances).
        wed_mid_session = _at(2026, 4, 22, 11, 0)
        nxt = next_market_open(wed_mid_session)
        assert nxt > wed_mid_session
        assert nxt.hour == 9 and nxt.minute == 30
