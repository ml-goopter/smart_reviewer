"""Term arithmetic. No database, no settings — the timezone is passed in.

Every expected value here is written as an explicit UTC instant rather than
computed, so a bug in the module cannot also produce the expectation.

America/Vancouver offsets in the tz database, which matter more than they look:

    ...  → 2026-03-08   PST, UTC-8
    2026-03-08 → 11-01  PDT, UTC-7
    2026-11-02 → ...    UTC-7 permanently, reported as "MST"

British Columbia legislated an end to seasonal clock changes, so the last
transition this zone ever makes is in November 2026 — after which winter is
UTC-7, not UTC-8. Anything that hardcodes -08:00 for a winter date, or assumes
"local midnight in December" is 08:00Z, is wrong from 2026 onward. This is the
strongest argument for computing terms on local dates: the zone's rules changed
under the code, and nothing in the code had to change with them.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.subscription_terms import (
    UnsupportedDurationUnit,
    add_term,
    compute_expires_at,
    is_active,
    last_valid_day,
    next_local_midnight,
)

TZ = ZoneInfo("America/Vancouver")


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class TestNextLocalMidnight:
    def test_late_local_evening_still_starts_the_term_tonight(self):
        # 23:30 on 12 Aug locally: the term starts half an hour later, at the
        # midnight ending the 12th — not a day after that.
        now = datetime(2026, 8, 12, 23, 30, tzinfo=TZ)
        assert next_local_midnight(now, TZ) == utc("2026-08-13T07:00:00")

    def test_a_utc_instant_already_past_midnight_reads_as_the_local_day(self):
        # 2026-08-13T06:00Z is 23:00 on the 12th in Vancouver. Taking the UTC
        # date here would start the term a day late.
        assert next_local_midnight(utc("2026-08-13T06:00:00"), TZ) == utc(
            "2026-08-13T07:00:00"
        )

    def test_midnight_local_rolls_to_the_next_day(self):
        now = datetime(2026, 8, 12, 0, 0, tzinfo=TZ)
        assert next_local_midnight(now, TZ) == utc("2026-08-13T07:00:00")


class TestCreate:
    def test_thirty_days_from_12_august(self):
        # local_midnight(13 Aug) + 30 days = 12 Sep 00:00 PDT.
        expires = compute_expires_at(None, 30, "day", utc("2026-08-12T20:00:00"), TZ)
        assert expires == utc("2026-09-12T07:00:00")

    def test_last_valid_day_is_the_day_before(self):
        expires = compute_expires_at(None, 30, "day", utc("2026-08-12T20:00:00"), TZ)
        assert last_valid_day(expires, TZ) == date(2026, 9, 11)

    def test_the_creation_day_is_free(self):
        # 12 Aug through 11 Sep inclusive is 31 usable days for a 30-day term,
        # because the term starts at the END of the creation day. Deliberate.
        expires = compute_expires_at(None, 30, "day", utc("2026-08-12T20:00:00"), TZ)
        assert (last_valid_day(expires, TZ) - date(2026, 8, 12)).days + 1 == 31

    def test_three_hundred_and_sixty_five_days_is_the_backfill_term(self):
        expires = compute_expires_at(None, 365, "day", utc("2026-08-12T20:00:00"), TZ)
        assert expires == utc("2027-08-13T07:00:00")
        assert last_valid_day(expires, TZ) == date(2027, 8, 12)


class TestRenewal:
    def test_early_renewal_extends_from_the_current_expiry(self):
        # Expires 12 Sep, renewed on 3 Sep: the 9 remaining days are kept, so
        # the new last valid day is 11 Oct — not 3 Oct.
        current = utc("2026-09-12T07:00:00")
        renewed = compute_expires_at(current, 30, "day", utc("2026-09-03T18:00:00"), TZ)
        assert renewed == utc("2026-10-12T07:00:00")
        assert last_valid_day(renewed, TZ) == date(2026, 10, 11)

    def test_lapsed_renewal_restarts_from_today(self):
        # Expired six weeks ago. The dead time is not credited back.
        current = utc("2026-07-01T07:00:00")
        renewed = compute_expires_at(current, 30, "day", utc("2026-08-12T20:00:00"), TZ)
        assert renewed == utc("2026-09-12T07:00:00")

    def test_renewal_on_the_expiry_day_itself_does_not_lose_that_day(self):
        # `now` is during 11 Sep, the last valid day; `current` is the midnight
        # that ends it. max() picks `current`, so the term is not shortened.
        current = utc("2026-09-12T07:00:00")
        renewed = compute_expires_at(current, 30, "day", utc("2026-09-11T20:00:00"), TZ)
        assert renewed == utc("2026-10-12T07:00:00")


class TestOffsetChanges:
    """Terms that span a change in the zone's UTC offset.

    The property every case asserts is the same: the term ends at local
    midnight. `timedelta(days=n)` on an aware datetime adds absolute time and
    would land an hour either side of it.
    """

    def test_term_crossing_the_last_real_dst_transition(self):
        # 21 Feb 00:00 PST (-08) + 30 days crosses 8 Mar 2026, the final spring
        # change this zone ever makes, so the term ends in PDT (-07).
        expires = compute_expires_at(None, 30, "day", utc("2026-02-20T20:00:00"), TZ)
        assert expires == utc("2026-03-23T07:00:00")
        assert expires.astimezone(TZ).hour == 0
        assert last_valid_day(expires, TZ) == date(2026, 3, 22)

    def test_term_crossing_the_permanent_switch(self):
        # 21 Oct 00:00 + 30 days crosses 2 Nov 2026, when the zone stops
        # observing DST for good. The offset happens to be -07 on both sides;
        # what is asserted is that the end is still midnight, whatever the
        # naming.
        expires = compute_expires_at(None, 30, "day", utc("2026-10-20T20:00:00"), TZ)
        assert expires == utc("2026-11-20T07:00:00")
        assert expires.astimezone(TZ).hour == 0
        assert last_valid_day(expires, TZ) == date(2026, 11, 19)

    def test_a_winter_term_after_the_switch_is_utc_minus_seven(self):
        # Guards the assumption this change invalidates: winter in Vancouver is
        # no longer -08:00, so a January midnight is 07:00Z, not 08:00Z.
        expires = compute_expires_at(None, 30, "day", utc("2027-01-10T20:00:00"), TZ)
        assert expires == utc("2027-02-10T07:00:00")
        assert expires.astimezone(TZ).hour == 0

    def test_a_year_long_term_ends_at_local_midnight(self):
        expires = compute_expires_at(None, 365, "day", utc("2026-11-05T20:00:00"), TZ)
        assert expires == utc("2027-11-06T07:00:00")
        assert expires.astimezone(TZ).hour == 0


class TestLastValidDay:
    def test_reads_the_boundary_in_the_operator_zone_not_utc(self):
        # 2026-09-12T07:00Z is 00:00 on the 12th in Vancouver, so the last day
        # is the 11th. Read as UTC it would be the 12th — off by one.
        assert last_valid_day(utc("2026-09-12T07:00:00"), TZ) == date(2026, 9, 11)

    def test_a_february_boundary_in_a_non_leap_year(self):
        assert last_valid_day(utc("2027-03-01T07:00:00"), TZ) == date(2027, 2, 28)


class TestIsActive:
    EXPIRES = utc("2026-09-12T07:00:00")

    def test_active_one_second_before_expiry(self):
        assert is_active("ACTIVE", self.EXPIRES, utc("2026-09-12T06:59:59"))

    def test_inactive_exactly_at_expiry(self):
        # Strictly `now < expires_at`. The boundary instant is already over.
        assert not is_active("ACTIVE", self.EXPIRES, self.EXPIRES)

    @pytest.mark.parametrize("status", ["CANCELLED", "PAUSED"])
    def test_suspension_closes_the_gate_regardless_of_expiry(self, status):
        assert not is_active(status, self.EXPIRES, utc("2026-08-12T20:00:00"))


class TestRejectedInput:
    @pytest.mark.parametrize("unit", ["month", "year"])
    def test_units_the_schema_allows_but_nothing_implements(self, unit):
        with pytest.raises(UnsupportedDurationUnit):
            compute_expires_at(None, 1, unit, utc("2026-08-12T20:00:00"), TZ)

    def test_unknown_unit(self):
        with pytest.raises(UnsupportedDurationUnit):
            compute_expires_at(None, 1, "fortnight", utc("2026-08-12T20:00:00"), TZ)

    @pytest.mark.parametrize("duration", [0, -1])
    def test_non_positive_duration(self, duration):
        with pytest.raises(ValueError):
            add_term(utc("2026-08-13T07:00:00"), duration, "day", TZ)
