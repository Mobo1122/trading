"""US equity-options market hours helpers.

Hand-rolled rather than pulling in `exchange_calendars` because we only
need NYSE regular-session bounds and a small holiday list. If the system
runs into 2027 these constants need extending.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

# NYSE regular session for options.
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)

# Half-day close used on the dates listed below in EARLY_CLOSE_DATES.
EARLY_CLOSE_TIME = time(13, 0)

# Full-day market closures. Update annually — these are NYSE observed dates.
HOLIDAYS_2026 = frozenset(
    {
        date(2026, 1, 1),    # New Year's Day
        date(2026, 1, 19),   # MLK Day
        date(2026, 2, 16),   # Presidents Day
        date(2026, 4, 3),    # Good Friday
        date(2026, 5, 25),   # Memorial Day
        date(2026, 6, 19),   # Juneteenth
        date(2026, 7, 3),    # Independence Day (observed; July 4 is Saturday)
        date(2026, 9, 7),    # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    }
)

HOLIDAYS_2027 = frozenset(
    {
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),   # Juneteenth observed (Saturday)
        date(2027, 7, 5),    # Independence Day observed (Sunday)
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),  # Christmas observed (Saturday)
    }
)

ALL_HOLIDAYS: frozenset[date] = HOLIDAYS_2026 | HOLIDAYS_2027

# Dates the market closes early at 1pm ET. Update annually.
EARLY_CLOSE_DATES: frozenset[date] = frozenset(
    {
        date(2026, 7, 2),     # day before July 4 weekend
        date(2026, 11, 27),   # day after Thanksgiving
        date(2026, 12, 24),   # Christmas Eve
        date(2027, 11, 26),
        date(2027, 12, 23),
    }
)


def is_market_open(now: datetime | None = None) -> bool:
    """Return True if NYSE regular-session is currently open.

    Uses the wall-clock time in `America/New_York`. Treats weekends and
    listed holidays as closed. On early-close dates the market closes at
    1pm ET instead of 4pm.
    """
    now_et = (now or datetime.now(timezone.utc)).astimezone(NY_TZ)

    if now_et.weekday() >= 5:  # Sat=5, Sun=6
        return False

    today = now_et.date()
    if today in ALL_HOLIDAYS:
        return False

    close = EARLY_CLOSE_TIME if today in EARLY_CLOSE_DATES else REGULAR_CLOSE
    return REGULAR_OPEN <= now_et.time() < close


def next_market_open(now: datetime | None = None) -> datetime:
    """Return the next datetime the market opens (in NY tz).

    Useful for the scheduler to sleep efficiently outside market hours
    instead of polling every minute.
    """
    now_et = (now or datetime.now(timezone.utc)).astimezone(NY_TZ)
    candidate = now_et.replace(
        hour=REGULAR_OPEN.hour,
        minute=REGULAR_OPEN.minute,
        second=0,
        microsecond=0,
    )

    if candidate <= now_et:
        candidate = candidate + timedelta(days=1)

    while (
        candidate.weekday() >= 5
        or candidate.date() in ALL_HOLIDAYS
    ):
        candidate = candidate + timedelta(days=1)

    return candidate
