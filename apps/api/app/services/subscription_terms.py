"""The arithmetic behind a subscription's `expires_at`.

Pure functions over datetimes — no database, no models, no settings beyond the
operator's timezone, which is passed in. Everything subtle about subscriptions
lives here, so it is all testable without a schema.

The rule, in one line: a term ends at an **exclusive** midnight, so a merchant
is active while `now < expires_at` and their last usable day is the day *before*
the stored timestamp.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

# The schema accepts all three so it never needs revisiting; only `day` is
# implemented. Months and years need end-of-month clamping (what is 31 Jan plus
# one month?) and no product requirement has asked for one.
DURATION_UNITS = ("day", "month", "year")
IMPLEMENTED_DURATION_UNITS = ("day",)


class UnsupportedDurationUnit(ValueError):
    """A unit the schema allows but this module does not implement yet."""


def next_local_midnight(now: datetime, tz: ZoneInfo) -> datetime:
    """The first instant of tomorrow, local to `tz`, as UTC.

    This is where a term starts counting, which is why the remainder of the
    creation day is free: a merchant signed at 16:00 gets a whole first day.
    """
    tomorrow = now.astimezone(tz).date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=tz).astimezone(UTC)


def add_term(base: datetime, duration: int, unit: str, tz: ZoneInfo) -> datetime:
    """Advance `base` by a term, in local calendar terms.

    Never `base + timedelta(days=n)`. That adds n x 24h of absolute time, so a
    term crossing a clock change lands at 23:00 or 01:00 local and the merchant
    gains or loses an hour of their last day. Adding to the local *date* and
    re-attaching midnight keeps every term ending exactly at midnight.
    """
    if unit not in IMPLEMENTED_DURATION_UNITS:
        raise UnsupportedDurationUnit(unit)
    if duration <= 0:
        raise ValueError("duration must be positive")

    local = base.astimezone(tz)
    end = local.date() + timedelta(days=duration)
    return datetime.combine(end, local.time(), tzinfo=tz).astimezone(UTC)


def compute_expires_at(
    current: datetime | None,
    duration: int,
    unit: str,
    now: datetime,
    tz: ZoneInfo,
) -> datetime:
    """The new `expires_at` for a create or a renewal.

    Renewal extends from the later of the current expiry and today, so renewing
    early never burns days already paid for, and a subscription that lapsed
    months ago is not credited the dead time. One expression covers both, and
    covers creation too when `current` is None.
    """
    floor = next_local_midnight(now, tz)
    base = max(current, floor) if current is not None else floor
    return add_term(base, duration, unit, tz)


def last_valid_day(expires_at: datetime, tz: ZoneInfo) -> date:
    """The last day the merchant's link works, local to `tz`.

    `expires_at` names the first *dead* midnight, so displaying it directly
    credits the merchant a day they do not have. Everything customer- or
    operator-facing shows this instead.
    """
    return expires_at.astimezone(tz).date() - timedelta(days=1)


def is_active(status: str, expires_at: datetime, now: datetime) -> bool:
    """The gate. Strictly `<`: at exactly `expires_at` the term is over."""
    return status == "ACTIVE" and now < expires_at
